"""Discordi teavitused webhookidega: kanal valitakse tunniplaani rühma (või ainekoodi) järgi."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field

from .tunniplaan import _ssl_context


@dataclass
class Channel:
    name: str
    webhook: str
    groups: list[str] = field(default_factory=list)   # nt ["Rakendusinformaatika 1. kursus"]
    codes: list[str] = field(default_factory=list)    # nt ["HKI5113.HK"]
    all: bool = False                                   # kõik loengud (nt #kalbergi-kursused)


def channels_for(channels: list[Channel], group: str | None, code: str | None) -> list[Channel]:
    g = (group or "").casefold()
    out = []
    for ch in channels:
        if ch.all or (code and code in ch.codes) or any(x.casefold() == g for x in ch.groups if g):
            out.append(ch)
    return out


def build_payload(title: str, video_id: str, course: str, summary: str | None, n_chapters: int,
                  materials_url: str | None) -> dict:
    desc = (summary or "").strip()
    if n_chapters:
        desc += f"\n\n📑 {n_chapters} peatükki · subtiitrid eesti keeles"
    if materials_url:
        desc += f"\n📂 [Materjalid ja transkriptsioon]({materials_url})"
    return {
        "username": "Loengusalvestused",
        "content": f"🎬 Uus loengusalvestus: **{title}**\nhttps://youtu.be/{video_id}",
        "embeds": [{
            "title": title[:256],
            "url": f"https://youtu.be/{video_id}",
            "description": desc[:4000],
            "color": 0xE52D27,
            "footer": {"text": course[:2048]},
            "thumbnail": {"url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"},
        }],
        "allowed_mentions": {"parse": []},
    }


def post(webhook: str, payload: dict, timeout: int = 30) -> None:
    req = urllib.request.Request(webhook, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "User-Agent": "loengud/0.1"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        if r.status >= 300:
            raise RuntimeError(f"Discord vastas {r.status}")
