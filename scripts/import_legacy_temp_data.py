#!/usr/bin/env python3
"""
Convert legacy JSON voice dumps from temp/tts-data into current raw schema.

This script is intentionally best-effort:
- If temp/tts-data does not exist, it exits successfully.
- If no JSON files are present, it exits successfully.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def infer_engine_and_platform(filename: str) -> tuple[str, str]:
    stem = filename.replace(".json", "")
    if stem == "avsynth":
        return ("AVSynth", "macos")
    if stem == "espeak":
        return ("eSpeak", "linux")
    if stem.endswith("-sapi") or "sapi" in stem:
        vendor = stem.split("-")[0].capitalize()
        return (f"{vendor} SAPI", "windows")
    if "-" in stem:
        vendor = stem.split("-")[0].capitalize()
        return (vendor, "windows")
    return (stem.capitalize(), "windows")


def normalize_gender(gender: Any) -> str:
    if gender is None:
        return "Unknown"
    value = str(gender).strip().lower()
    if value in {"m", "male"}:
        return "Male"
    if value in {"f", "female"}:
        return "Female"
    return "Unknown"


def convert_file(src: Path, dst_dir: Path) -> tuple[Path, int]:
    if src.stem == "microsoft-sapi":
        # Runtime Windows SAPI collection already covers this set.
        out_path = dst_dir / "windows-voices.json"
        return (out_path, 0)

    data = json.loads(src.read_text(encoding="utf-8"))
    out_path = dst_dir / f"static-{src.stem}-voices.json"
    if not isinstance(data, list):
        return (out_path, 0)

    engine, platform = infer_engine_and_platform(src.name)
    now = datetime.now(timezone.utc).isoformat()
    optional_fields = ["preview_audio", "quality", "styles", "software", "age"]

    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        voice = {
            "id": item.get("id", ""),
            "name": item.get("name", "Unknown"),
            "language_codes": item.get("language_codes", []),
            "gender": normalize_gender(item.get("gender")),
            "engine": engine,
            "platform": platform,
            "collected_at": now,
            "source_type": "static",
            "source_name": src.name,
        }
        for key in optional_fields:
            value = item.get(key)
            if value is not None:
                voice[key] = value
        out.append(voice)

    new_count = len(out)
    existing_count = -1
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                existing_count = len(existing)
        except Exception:
            existing_count = -1

    if existing_count >= 0 and new_count < existing_count:
        print(
            f"Keeping existing {out_path.name}: "
            f"{existing_count} voices > new {new_count}"
        )
        return (out_path, existing_count)

    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return (out_path, new_count)


def main() -> int:
    project_root = Path(__file__).parent.parent
    legacy_dir = project_root / "temp" / "tts-data"
    out_dir = project_root / "data" / "raw"

    if not legacy_dir.exists():
        print(f"Legacy directory not found: {legacy_dir} (skipping)")
        return 0

    files = sorted(legacy_dir.glob("*.json"))
    if not files:
        print(f"No legacy files found in {legacy_dir} (skipping)")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for src in files:
        if src.stem == "microsoft-sapi":
            print(f"Skipping {src.name}: covered by windows-voices.json")
            continue
        out_path, count = convert_file(src, out_dir)
        total += count
        print(f"Converted {src.name:26s} -> {out_path.name:36s} ({count} voices)")

    print(f"\nConverted {len(files)} files, total voices: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
