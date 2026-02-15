#!/usr/bin/env python3
"""
Export a static JSON payload for the frontend site from data/voices.db.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_json_field(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return json.loads(text)
        except Exception:
            return default
    return default


def normalize_gender(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"m", "male"}:
        return "Male"
    if text in {"f", "female"}:
        return "Female"
    # "n" and "neutral" are treated as unknown for this catalog UI.
    if text in {"n", "neutral", "none", "unknown", ""}:
        return "Unknown"
    return "Unknown"


def normalize_engine(engine: str) -> str:
    return "".join(ch for ch in str(engine).lower() if ch.isalnum())


def is_cross_platform_local_engine(engine: str) -> bool:
    engine_norm = normalize_engine(engine)
    return engine_norm in {"sherpaonnx", "espeak"}


def mode_from_platform(platform: str, engine: str) -> str:
    # Sherpa-ONNX is an offline/local engine even if collected in online job mode.
    if is_cross_platform_local_engine(engine):
        return "offline"
    return "online" if platform == "online" else "offline"


def platform_display(platform: str, engine: str) -> str:
    if is_cross_platform_local_engine(engine):
        return "cross-platform"
    return platform


def build_payload(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            voice_key, id, name, language_codes, gender, engine, platform,
            collected_at, language_name, language_display, country_code,
            script, latitude, longitude, geo_country, geo_region,
            written_script, preview_audio, preview_audios, quality,
            styles, software, age, source_type, source_name
        FROM voices
        """
    ).fetchall()
    conn.close()

    voices: list[dict[str, Any]] = []
    platforms = Counter()
    engines = Counter()
    genders = Counter()
    countries: dict[str, dict[str, Any]] = {}
    country_modes: dict[str, Counter[str]] = defaultdict(Counter)
    country_lat_sum: dict[str, float] = defaultdict(float)
    country_lon_sum: dict[str, float] = defaultdict(float)
    country_points: dict[str, int] = defaultdict(int)

    for row in rows:
        language_codes = parse_json_field(row["language_codes"], [])
        styles = parse_json_field(row["styles"], [])
        preview_audios = parse_json_field(row["preview_audios"], [])

        platform = (row["platform"] or "unknown").strip().lower()
        mode = mode_from_platform(platform, row["engine"])
        country_code = (row["country_code"] or "ZZ").upper()
        country_name = row["geo_country"] or row["language_display"] or "Unknown"

        voice = {
            "voice_key": row["voice_key"],
            "id": row["id"],
            "name": row["name"],
            "language_codes": language_codes,
            "gender": normalize_gender(row["gender"]),
            "engine": row["engine"],
            "platform": platform,
            "platform_display": platform_display(platform, row["engine"]),
            "mode": mode,
            "country_code": country_code,
            "country_name": country_name,
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "language_name": row["language_name"],
            "language_display": row["language_display"],
            "script": row["script"],
            "geo_region": row["geo_region"],
            "written_script": row["written_script"],
            "preview_audio": row["preview_audio"],
            "preview_audios": preview_audios,
            "quality": row["quality"],
            "styles": styles,
            "software": row["software"],
            "age": row["age"],
            "source_type": row["source_type"],
            "source_name": row["source_name"],
            "collected_at": row["collected_at"],
        }
        voices.append(voice)

        platforms[platform] += 1
        engines[row["engine"]] += 1
        genders[voice["gender"]] += 1

        if country_code not in countries:
            countries[country_code] = {
                "country_code": country_code,
                "country_name": country_name,
                "count": 0,
                "online_count": 0,
                "offline_count": 0,
                "latitude": None,
                "longitude": None,
            }

        countries[country_code]["count"] += 1
        country_modes[country_code][mode] += 1
        if mode == "online":
            countries[country_code]["online_count"] += 1
        else:
            countries[country_code]["offline_count"] += 1

        lat = row["latitude"]
        lon = row["longitude"]
        if lat is not None and lon is not None:
            country_lat_sum[country_code] += float(lat)
            country_lon_sum[country_code] += float(lon)
            country_points[country_code] += 1

    for code, item in countries.items():
        if country_points[code] > 0:
            item["latitude"] = country_lat_sum[code] / country_points[code]
            item["longitude"] = country_lon_sum[code] / country_points[code]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "voices": len(voices),
            "platforms": dict(platforms),
            "engines": len(engines),
            "countries": len(countries),
            "online": sum(1 for v in voices if v["mode"] == "online"),
            "offline": sum(1 for v in voices if v["mode"] == "offline"),
        },
        "facets": {
            "platforms": dict(platforms),
            "engines": dict(engines),
            "genders": dict(genders),
        },
        "countries": sorted(countries.values(), key=lambda x: x["count"], reverse=True),
        "voices": voices,
    }

    return payload


def write_payload(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    project_root = Path(__file__).parent.parent
    db_path = project_root / "data" / "voices.db"
    out_paths = [project_root / "data" / "static" / "voices-site.json"]
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1
    payload = build_payload(db_path)
    for out_path in out_paths:
        write_payload(payload, out_path)
        print(f"Wrote {out_path}")
    count = int(payload.get("summary", {}).get("voices", 0))
    print(f"Exported {count} voices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
