"""YouTube Data API: üleslaadimine (api-režiim), video leidmine (studio-režiim), subtiitrid, esitusloend."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .config import YoutubeConfig

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


class YoutubeError(RuntimeError):
    pass


def get_service(cfg: YoutubeConfig, interactive: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = None
    if cfg.token.exists():
        creds = Credentials.from_authorized_user_file(str(cfg.token), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        cfg.token.write_text(creds.to_json(), encoding="utf-8")
    if not creds or not creds.valid:
        if not interactive:
            raise YoutubeError("YouTube'i token puudub või aegus – käivita `loengud auth`.")
        from google_auth_oauthlib.flow import InstalledAppFlow
        if not cfg.client_secrets.exists():
            raise YoutubeError(f"OAuth client secret puudub: {cfg.client_secrets} (vt README, samm 3).")
        flow = InstalledAppFlow.from_client_secrets_file(str(cfg.client_secrets), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
        cfg.token.parent.mkdir(parents=True, exist_ok=True)
        cfg.token.write_text(creds.to_json(), encoding="utf-8")
        cfg.token.chmod(0o600)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# --- pealkirjad / failinimed -------------------------------------------------

def safe_filename(title: str) -> str:
    t = re.sub(r"[/\\:]+", " -", title)
    t = re.sub(r"[\x00-\x1f\"<>|?*]", "", t)
    return re.sub(r"\s+", " ", t).strip()[:180]


def norm_title(title: str) -> str:
    t = unicodedata.normalize("NFC", safe_filename(title)).casefold()
    t = re.sub(r"\.(mp4|mov|m4v)$", "", t)
    return re.sub(r"[\s\-–—]+", " ", t).strip()


# --- toimingud -----------------------------------------------------------------

def upload_video(service, path: Path, title: str, description: str, cfg: YoutubeConfig, log=print) -> str:
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "categoryId": cfg.category_id, "defaultLanguage": "et", "defaultAudioLanguage": "et"},
        "status": {"privacyStatus": cfg.privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(path), chunksize=64 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = service.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            log(f"  üleslaadimine {int(status.progress() * 100)}%")
    vid = resp["id"]
    actual = resp.get("status", {}).get("privacyStatus")
    if actual and actual != cfg.privacy:
        log(f"  HOIATUS: video privaatsus on '{actual}', mitte '{cfg.privacy}' – API-projekt pole ilmselt auditeeritud.")
    return vid


def find_uploaded_video(service, expected_title: str, max_pages: int = 3) -> str | None:
    ch = service.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items") or []
    if not items:
        raise YoutubeError("Autenditud kontol pole YouTube'i kanalit.")
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    want = norm_title(expected_title)
    token = None
    for _ in range(max_pages):
        resp = service.playlistItems().list(part="snippet", playlistId=uploads, maxResults=50,
                                            pageToken=token).execute()
        for it in resp.get("items", []):
            if norm_title(it["snippet"]["title"]) == want:
                return it["snippet"]["resourceId"]["videoId"]
        token = resp.get("nextPageToken")
        if not token:
            break
    return None


def update_metadata(service, video_id: str, title: str, description: str, cfg: YoutubeConfig,
                    set_privacy: bool = True, log=print) -> None:
    cur = service.videos().list(part="snippet,status", id=video_id).execute().get("items", [])
    if not cur:
        raise YoutubeError(f"Videot {video_id} ei leitud.")
    snip = cur[0]["snippet"]
    body = {"id": video_id, "snippet": {
        "title": title[:100], "description": description[:4900],
        "categoryId": snip.get("categoryId", cfg.category_id),
        "defaultLanguage": "et", "defaultAudioLanguage": "et",
        "tags": snip.get("tags", []),
    }}
    parts = "snippet"
    if set_privacy:
        st = cur[0]["status"]
        body["status"] = {"privacyStatus": cfg.privacy,
                          "selfDeclaredMadeForKids": st.get("selfDeclaredMadeForKids", False),
                          "embeddable": st.get("embeddable", True)}
        parts = "snippet,status"
    try:
        service.videos().update(part=parts, body=body).execute()
    except Exception as e:  # noqa: BLE001
        if set_privacy:
            log(f"  privaatsuse muutmine ebaõnnestus ({e}); uuendan ainult pealkirja/kirjelduse")
            update_metadata(service, video_id, title, description, cfg, set_privacy=False, log=log)
        else:
            raise


def upsert_captions(service, video_id: str, srt_path: Path, cfg: YoutubeConfig) -> str:
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(srt_path), mimetype="application/octet-stream", resumable=False)
    existing = service.captions().list(part="snippet", videoId=video_id).execute().get("items", [])
    for c in existing:
        s = c["snippet"]
        if s.get("language") == cfg.caption_language and s.get("name") == cfg.caption_name:
            service.captions().update(part="id", body={"id": c["id"]}, media_body=media).execute()
            return c["id"]
    body = {"snippet": {"videoId": video_id, "language": cfg.caption_language,
                        "name": cfg.caption_name, "isDraft": False}}
    resp = service.captions().insert(part="snippet", body=body, media_body=media).execute()
    return resp["id"]


def ensure_in_playlist(service, playlist_id: str, video_id: str) -> bool:
    resp = service.playlistItems().list(part="id", playlistId=playlist_id, videoId=video_id).execute()
    if resp.get("items"):
        return False
    service.playlistItems().insert(part="snippet", body={"snippet": {
        "playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
    return True
