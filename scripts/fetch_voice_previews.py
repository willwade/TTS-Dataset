#!/usr/bin/env python3
"""
Fetch and update preview-audio reference maps used by harmonize.py.

Outputs:
- data/reference/acapela_voice_previews.json  (list)
- data/reference/azure_voice_previews.json    (dict name->url)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


def _safe_message(text: str) -> str:
    return text.encode("ascii", errors="replace").decode("ascii")


def _read_existing_count(path: Path, expect_list: bool) -> int:
    if not path.exists():
        return -1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if expect_list and isinstance(data, list):
            return len(data)
        if (not expect_list) and isinstance(data, dict):
            return len(data)
    except Exception:
        return -1
    return -1


def _write_json_if_not_lower(path: Path, payload: Any, expect_list: bool) -> int:
    new_count = len(payload) if isinstance(payload, (list, dict)) else 0
    existing_count = _read_existing_count(path, expect_list=expect_list)
    if new_count == 0 and existing_count < 0:
        print(f"No entries returned for {path.name}; leaving file unchanged.")
        return 0
    if existing_count >= 0 and new_count < existing_count:
        print(f"Keeping existing {path.name}: {existing_count} entries > new {new_count}")
        return existing_count
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_count


def fetch_acapela_previews() -> list[dict[str, Any]]:
    url = "https://www.acapela-group.com/voices/repertoire/"
    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        },
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    voices_list: list[dict[str, Any]] = []

    voices = soup.find_all("div", class_="voice")
    for voice in voices:
        identity = voice.find("div", class_="identity")
        if not identity:
            continue
        name_node = identity.find("p", class_="name")
        voice_name = name_node.text.strip() if name_node else "Unknown"
        gender = voice.get("data-gender", "Unknown")
        demos = voice.find_all("div", class_="demo-item")
        for demo in demos:
            sound_player = demo.find("div", class_="sound-player")
            if not sound_player:
                continue
            preview_audio = sound_player.get("data-mp3", "")
            lang = sound_player.get("data-lang", "")
            quality_node = demo.find("p", {"data-label": "Quality"})
            quality = quality_node.text.strip() if quality_node else None
            if lang:
                voices_list.append(
                    {
                        "id": f"{voice_name}-{quality or 'default'}".replace(" ", "-").lower(),
                        "name": voice_name,
                        "language_codes": [lang],
                        "gender": gender,
                        "preview_audio": preview_audio,
                        "quality": quality,
                    }
                )
                break

    return voices_list


def fetch_azure_previews_playwright() -> dict[str, str]:
    """Fetch Microsoft voice previews via Playwright (dynamic page)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for Azure previews. "
            "Install with: uv add --dev playwright && playwright install chromium"
        ) from exc

    voice_previews: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://speech.microsoft.com/portal/voicegallery", wait_until="networkidle")
        page.wait_for_timeout(4000)
        cards = page.locator(".voice-card")
        count = cards.count()
        for i in range(count):
            card = cards.nth(i)
            try:
                title = card.locator(".voice-card-name").get_attribute("title") or ""
                src = card.locator("audio").get_attribute("src") or ""
                if title and src:
                    voice_previews[title] = src
            except Exception:
                continue
        browser.close()
    return voice_previews


def main() -> None:
    project_root = Path(__file__).parent.parent
    out_dir = project_root / "data" / "reference"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        acapela = fetch_acapela_previews()
        acapela_path = out_dir / "acapela_voice_previews.json"
        count = _write_json_if_not_lower(acapela_path, acapela, expect_list=True)
        if acapela_path.exists():
            print(f"Wrote {count} Acapela previews -> {acapela_path}")
    except Exception as e:
        print(_safe_message(f"Skipping Acapela preview update: {type(e).__name__}: {e}"))

    try:
        azure = fetch_azure_previews_playwright()
        azure_path = out_dir / "azure_voice_previews.json"
        count = _write_json_if_not_lower(azure_path, azure, expect_list=False)
        if azure_path.exists():
            print(f"Wrote {count} Azure previews -> {azure_path}")
    except Exception as e:
        print(_safe_message(f"Skipping Azure preview update: {type(e).__name__}: {e}"))


if __name__ == "__main__":
    main()
