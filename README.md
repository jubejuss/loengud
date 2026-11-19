# Loengute süsteemid · `loengud`

Töövoog, mis viib Teamsi loengusalvestuse YouTube'i eestikeelsete subtiitritega ja salvestab transkriptsiooni õige seminari alla loengurepos.

```
TLÜ OneDrive / Recordings (sünk Maci)
        │  uus .mp4, ≥20 min muutmata
        ▼
 kuupäev → .loengud.yaml ajakava → kursus + seminar
        ▼
 ffmpeg → 16 kHz WAV → TalTech est-asr-pipeline (tekstiks.ee mootor, Docker)
        ▼
 result.json → subtiitrid (SRT/VTT, 2×42 märki) + transkriptsioon.md
        ▼
 git commit + push  →  <repo>/<seminar>/salvestus/
        ▼
 YouTube: video (api- või studio-režiim) → subtiitrid (et) → kursuse esitusloend
        ▼
 (olemasolev Apps Script postitab uue playlisti-video Discordi)
```

Iga samm on idempotentne: olek on failis `~/.config/loengud/state.json`, katkestuse korral jätkab järgmine käivitus sealt, kus pooleli jäi.

## Miks mitte tekstiks.ee veebiteenus otse?

Tekstiks.ee veebiteenusel pole avalikku API-t, eksport on DOCX (ilma subtiitrite ajatempliteta) ja limiit on ~10 faili päevas. Sama mootor on aga avatud lähtekoodiga: [taltechnlp/est-asr-pipeline](https://github.com/taltechnlp/est-asr-pipeline). See töötab Dockeris sinu masinas ja annab `result.json`-i sõnatasemel ajatempli, kirjavahemärkide ja kõnelejatega.

## ⚠️ YouTube'i API piirang (oluline)

YouTube lukustab kõik videod, mis on üles laaditud **auditeerimata** Google Cloudi projektist (loodud pärast 28.07.2020), jäädavalt privaatseks. Seepärast on kaks režiimi:

| `youtube.upload_mode` | Kes video üles laeb | Mida skript teeb |
|---|---|---|
| `studio` (vaikimisi) | Sina YouTube Studios. Skript valmistab ette faili `~/Movies/Loengud-üleslaadimiseks/<pealkiri>.mp4`, mille lohistad Studiosse | leiab video pealkirja järgi, paneb õige pealkirja, kirjelduse ja privaatsuse (unlisted), lisab subtiitrid ja esitusloendi, uuendab transkriptsiooni videolingiga |
| `api` | Skript | kõik ülaltoodu + üleslaadimine. Vajab läbitud [YouTube API auditit](https://support.google.com/youtube/contact/yt_api_form) |

Subtiitrid, esitusloend ja metaandmed töötavad ilma auditita. Kui audit kunagi läbib, muuda režiimiks `api`.

## Paigaldus (Mac)

### 1. Eeldused

```bash
brew install ffmpeg openjdk@17 git
# Docker Desktop või OrbStack peab töötama
curl -s https://get.nextflow.io | bash && mkdir -p ~/.local/bin && mv nextflow ~/.local/bin/
git clone https://github.com/taltechnlp/est-asr-pipeline ~/tools/est-asr-pipeline
docker pull --platform linux/amd64 alumae/est-asr-pipeline:0.1.4
```

**Apple Silicon (M1 MacBook):** Dockeri pilt on ainult x86_64, seega jookseb see emulatsioonis ja on aeglane. Lisa seadistusse `asr.docker_run_options: "--platform linux/amd64 --memory=10g"`. **Inteli iMac** käitab pilti natiivselt ja on ASR-i jaoks parem valik. Mõõda esimese loengu peal, kui kaua see võtab: `~/Library/Caches/loengud/<id>/asr.log`.

### 2. Tööriist

```bash
cd loengute-systeemid
./install.sh            # venv + käsk ~/.local/bin/loengud + ~/.config/loengud/config.yaml
```

Muuda `~/.config/loengud/config.yaml` failis:
- `source.recordings_dirs`: TLÜ OneDrive'i sünkroonitud `Recordings` kaust (Finderis `~/Library/CloudStorage/OneDrive-…/Recordings`). Teams salvestab koosoleku korraldaja OneDrive'i.
- `repos`: loengurepode kohalikud kloonid.

### 3. YouTube OAuth

1. [Google Cloud Console](https://console.cloud.google.com/) → võid kasutada sama projekti, mis Discordi Apps Scripti jaoks, või luua uue.
2. *APIs & Services → Library*: lülita sisse **YouTube Data API v3**.
3. *OAuth consent screen*: tüüp External, staatus Testing, lisa test-kasutajaks oma Google'i konto (see, millele kuulub YouTube'i kanal).
4. *Credentials → Create credentials → OAuth client ID → Desktop app* → laadi JSON alla ja salvesta: `~/.config/loengud/client_secret.json`.
5. `loengud auth` avab brauseri. Vali kanal, kuhu loengud lähevad.

> Testing-staatusega OAuth-rakenduse refresh token aegub 7 päeva pärast. Et ajastatud töö ei katkeks, vii consent screen olekusse **In production**. Isiklikuks kasutuseks ei pea selleks läbima Google'i verifitseerimist: sisselogimisel näed hoiatust „unverified app“, mille saad vahele jätta.

### 4. Loengurepo ajakava

Igasse loengurepo juurkausta tuleb fail `.loengud.yaml` (mall: `loengud init --repo ~/Projects/loengud/rif25-veebiarendus`):

```yaml
course: "Veebiarendus (RIF25)"
match_title: "RIF25"          # valikuline: Teamsi koosoleku pealkirja alamstring
default_time: "10:00-13:15"   # valikuline: eristab sama päeva seminare
recording_subdir: salvestus
youtube:
  playlist_id: "PL…"          # sama playlist, mida Discordi Apps Script jälgib
  title_template: "{course} – {seminar_title} ({date_et})"
seminars:
  - date: 2026-11-19
    dir: seminarid/04-css-grid
    title: "Seminar 4: CSS Grid"
  - date: 2026-11-26
    dir: seminarid/05-flexbox
    title: "Seminar 5: Flexbox"
    time: "14:00-17:15"
```

Tulemus repos:

```
seminarid/04-css-grid/salvestus/
  transkriptsioon.md      # front matter + ajatempliga lõigud, ajatemplid on YouTube'i lingid
  subtiitrid.et.srt
  subtiitrid.et.vtt
```

Kui ühest seminarist on mitu salvestust (Teams jagab pika salvestuse või salvestus käivitati uuesti), saavad järgmised failid nime `transkriptsioon-2.md` ja video pealkirja lõppu „(osa 2)“.

**Sobitamise reeglid:** salvestuse algusaeg võetakse Teamsi failinimest (`…-20261119_081530-Meeting Recording.mp4`), varuvariandina ffprobe'ist või faili ajast. Seejärel otsitakse kõigist repodest seminar sama kuupäevaga. Kui samal päeval sobib mitu, kitsendatakse valikut `match_title` ja seejärel kellaaja (`time` / `default_time`, ±45 min) järgi. Kui seminari ei leita või neid on mitu, jääb salvestus ootele ja `loengud status` näitab põhjust.

> Kontrolli esimese salvestuse peal `loengud scan` väljundist, kas kellaaeg klapib. Kui see on 2 tundi nihkes, muuda `source.filename_tz` väärtust (`UTC` ↔ `Europe/Tallinn`).

### 5. Ajastus

```bash
loengud doctor          # kontrollib kõiki eeldusi
loengud scan            # kuivkäivitus: mis leiti ja kuhu see sobitub
loengud run             # päris käivitus
./install.sh --launchd  # käivitus iga 2 h taustal, logi: ~/Library/Logs/loengud.log
```

macOS võib taustaprotsessil keelata ligipääsu kaustale `~/Library/CloudStorage`. Kui logis on `Operation not permitted`, lisa *System Settings → Privacy & Security → Full Disk Access* alla venv-i Python (`~/.local/share/loengud/venv/bin/python3` → selle sihtfail).

## Igapäevane kasutus

| Olukord | Käsk |
|---|---|
| mis on pooleli / mis ootab | `loengud status` |
| salvestust ei sobitatud | `loengud assign "<fail.mp4>" --repo ~/…/repo --seminar seminarid/05-flexbox` |
| mitteloeng (nt koosolek) | `loengud ignore "<fail.mp4>"` |
| subtiitrite uuesti genereerimine pärast mingi muudatuse tegemist | `loengud retry "<fail.mp4>" --from transcribed` ja seejärel `loengud run` |
| teisendus käsitsi | `loengud subs result.json --out ./x` |

Studio-režiimis: kui `status` näitab „lae Studiosse üles: …mp4“, lohista see fail YouTube Studiosse (pealkirja ei pea muutma, failinimi on õige). Järgmine käivitus teeb ülejäänu.

## Arendus

```bash
pip install -e '.[dev]' && pytest
```

Testid kasutavad päris git-repot ja remote'i ning võlts-ASR-i ja võlts-YouTube'i API-t: `api`- ja `studio`-voog otsast lõpuni, idempotentsus, mitmeosaline salvestus, käsitsi määramine.

Moodulid: `source` (salvestuste leidmine) · `schedule` (ajakava ja sobitamine) · `asr` (ffmpeg + Nextflow) · `subtitles` (SRT/VTT/MD) · `youtube` · `gitops` · `pipeline` (olekumasin) · `cli`.
