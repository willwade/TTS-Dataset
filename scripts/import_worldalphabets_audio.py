#!/usr/bin/env python3
"""
Import WorldAlphabets audio preview data into a local reference index.

Input:
- WorldAlphabets data directory containing audio/*.wav

Output:
- data/reference/worldalphabets_audio_index.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def normalize_token(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def build_records(audio_dir: Path, url_base: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    pattern = re.compile(r"^(?P<lang>[^_]+)_(?P<engine>[^_]+)_(?P<voice>.+)\.wav$", re.IGNORECASE)

    for file in sorted(audio_dir.glob("*.wav")):
        match = pattern.match(file.name)
        if not match:
            continue
        language_code = match.group("lang")
        engine = match.group("engine")
        voice = match.group("voice")
        records.append(
            {
                "language_code": language_code,
                "engine": engine,
                "engine_norm": normalize_token(engine),
                "voice_id": voice,
                "voice_id_norm": normalize_token(voice),
                "url": f"{url_base.rstrip('/')}/{file.name}",
            }
        )
    return records


def write_if_not_lower(output_path: Path, payload: list[dict[str, str]]) -> int:
    new_count = len(payload)
    old_count = -1
    if output_path.exists():
        try:
            current = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(current, list):
                old_count = len(current)
        except Exception:
            old_count = -1

    if old_count >= 0 and new_count < old_count:
        print(f"Keeping existing {output_path.name}: {old_count} entries > new {new_count}")
        return old_count

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import WorldAlphabets audio previews")
    parser.add_argument(
        "--source",
        default="C:/github/WorldAlphabets/data",
        help="Path to WorldAlphabets data directory",
    )
    parser.add_argument(
        "--url-base",
        default="https://raw.githubusercontent.com/willwade/WorldAlphabets/main/data/audio",
        help="URL prefix for generated preview audio links",
    )
    args = parser.parse_args()

    source_dir = Path(args.source)
    audio_dir = source_dir / "audio"
    if not audio_dir.exists():
        raise SystemExit(f"Audio directory not found: {audio_dir}")

    records = build_records(audio_dir, args.url_base)
    project_root = Path(__file__).parent.parent
    output_path = project_root / "data" / "reference" / "worldalphabets_audio_index.json"
    count = write_if_not_lower(output_path, records)
    print(f"Wrote {count} records to {output_path}")


if __name__ == "__main__":
    main()
