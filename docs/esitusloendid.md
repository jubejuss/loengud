# YouTube'i kanal ja esitusloendid

Kanal: **Juho Kalberg** (@JuhoKalberg), `UC0Alra3aIM0AukJtJDErDVA`. Google'i konto: jubejuss@gmail.com.

## Ühine esitusloend (iga loeng)

Määratud failis `~/.config/loengud/config.yaml` → `youtube.common_playlist_ids`.

| Esitusloend | ID |
|---|---|
| Haapsalu kolledž | `PL2lxpfi7Jl2uqRbh4Ew7v0jdKjteolb4_` |

## Kursuste esitusloendid

Iga loengurepo `.loengud.yaml` failis → `youtube.playlist_id`.

| Esitusloend | ID | Discord (Apps Script) |
|---|---|---|
| SJTA (Sissejuhatus tarkvaraarendusse) | `PL2lxpfi7Jl2tM77rwR4afo9u97yZpWr8L` | ✓ jälgib |
| Raamistikud (Veebiraamistikud) | `PL2lxpfi7Jl2udZVMkfKQCMuZ5sGvOxLQ8` | ✓ jälgib |
| Kasutajaliideste disain | `PL2lxpfi7Jl2s4ih7WblvnSDEHLD8QbzRZ` | |
| Sisuhaldussüsteemid | `PL2lxpfi7Jl2uw3kL5axcbDloj_nHTmg8g` | |
| Eesrakenduste arendamine | `PL2lxpfi7Jl2vrR-mpmHtTr2VmGq_MI8SN` | |
| Veebirakendused | `PL2lxpfi7Jl2uN6J3IX8mrmpK_aY5Vwzzq` | |
| Käsitöö eriala | `PL2lxpfi7Jl2tx0ZqhfvRTVIiemuv2SUBp` | |

Näide (`.loengud.yaml`):

```yaml
course: "Sissejuhatus tarkvaraarendusse"
youtube:
  playlist_id: "PL2lxpfi7Jl2tM77rwR4afo9u97yZpWr8L"   # SJTA
  # extra_playlist_ids: []   # vajadusel veel kursusepõhiseid loendeid
```

> Ühise ja kursuse esitusloendi duplikaadid eemaldatakse automaatselt. Video lisamine on idempotentne – kui video on loendis juba olemas, seda uuesti ei lisata.
