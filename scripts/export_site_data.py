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


def load_country_population(reference_path: Path) -> dict[str, int]:
    if not reference_path.exists():
        return {}
    try:
        payload = json.loads(reference_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    countries = payload.get("countries", {})
    if not isinstance(countries, dict):
        return {}
    out: dict[str, int] = {}
    for code, value in countries.items():
        c = str(code or "").upper().strip()
        if len(c) != 2:
            continue
        try:
            pop = int(value)
        except Exception:
            continue
        if pop > 0:
            out[c] = pop
    return out


def load_language_speakers(
    reference_path: Path,
) -> tuple[dict[str, dict[str, Any]], int]:
    if not reference_path.exists():
        return {}, 0
    try:
        payload = json.loads(reference_path.read_text(encoding="utf-8"))
    except Exception:
        return {}, 0

    languages = payload.get("languages", [])
    if not isinstance(languages, list):
        return {}, 0

    by_qid: dict[str, dict[str, Any]] = {}
    for item in languages:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("qid") or "").strip()
        if not qid:
            continue
        try:
            speakers = int(item.get("speakers") or 0)
        except Exception:
            continue
        if speakers <= 0:
            continue
        iso1 = {
            str(code).lower().strip()
            for code in item.get("iso639_1", [])
            if isinstance(code, str) and len(code.strip()) == 2
        }
        iso3 = {
            str(code).lower().strip()
            for code in item.get("iso639_3", [])
            if isinstance(code, str) and len(code.strip()) == 3
        }
        by_qid[qid] = {
            "qid": qid,
            "name": item.get("name"),
            "speakers": speakers,
            "iso1": iso1,
            "iso3": iso3,
        }

    return by_qid, sum(int(v["speakers"]) for v in by_qid.values())


def normalize_primary_language_tag(code: str) -> str:
    value = str(code or "").strip().lower().replace("_", "-")
    if not value:
        return ""
    primary = value.split("-", 1)[0]
    # Historical / non-standard aliases commonly seen in voice catalogs.
    alias = {
        "iw": "he",
        "in": "id",
        "ji": "yi",
        "jw": "jv",
    }
    return alias.get(primary, primary)


def build_payload(db_path: Path) -> dict[str, Any]:
    population_by_country = load_country_population(
        db_path.parent / "reference" / "country-population.json"
    )
    total_world_population = sum(population_by_country.values())
    language_speakers_by_qid, total_language_speakers = load_language_speakers(
        db_path.parent / "reference" / "language-speakers.json"
    )
    language_by_iso1: dict[str, tuple[str, int]] = {}
    language_by_iso3: dict[str, tuple[str, int]] = {}
    for qid, item in language_speakers_by_qid.items():
        speakers = int(item["speakers"])
        for code in item["iso1"]:
            prev = language_by_iso1.get(code)
            if prev is None or speakers > prev[1]:
                language_by_iso1[code] = (qid, speakers)
        for code in item["iso3"]:
            prev = language_by_iso3.get(code)
            if prev is None or speakers > prev[1]:
                language_by_iso3[code] = (qid, speakers)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            voice_key, id, name, language_codes, gender, engine, platform,
            collected_at, language_name, language_display, country_code,
            script, latitude, longitude, geo_country, geo_region,
            written_script, preview_audio, preview_audios, quality,
            styles, software, age, model_type, developer, num_speakers,
            sample_rate, runtime, provider, engine_family, distribution_channel,
            capability_tags, taxonomy_source, taxonomy_confidence, source_type, source_name
        FROM voices
        """
    ).fetchall()
    solution_rows = conn.execute(
        """
        SELECT solution_id, category, support_level, COUNT(*) AS voice_count
        FROM solution_voice_matches
        GROUP BY solution_id, category, support_level
        """
    ).fetchall()
    solution_meta = conn.execute(
        """
        SELECT id, name, category, vendor, platforms, links
        FROM solutions
        """
    ).fetchall()
    solution_runtime_support = conn.execute(
        """
        SELECT solution_id, runtime, runtime_class, support_level, mode, notes
        FROM solution_runtime_support
        """
    ).fetchall()
    solution_provider_support = conn.execute(
        """
        SELECT solution_id, provider, support_level, mode, notes
        FROM solution_provider_support
        """
    ).fetchall()
    conn.close()

    voices: list[dict[str, Any]] = []
    platforms = Counter()
    engines = Counter()
    genders = Counter()
    runtimes = Counter()
    providers = Counter()
    engine_families = Counter()
    distribution_channels = Counter()
    countries: dict[str, dict[str, Any]] = {}
    country_modes: dict[str, Counter[str]] = defaultdict(Counter)
    country_lat_sum: dict[str, float] = defaultdict(float)
    country_lon_sum: dict[str, float] = defaultdict(float)
    country_points: dict[str, int] = defaultdict(int)

    for row in rows:
        language_codes = parse_json_field(row["language_codes"], [])
        styles = parse_json_field(row["styles"], [])
        preview_audios = parse_json_field(row["preview_audios"], [])
        capability_tags = parse_json_field(row["capability_tags"], [])

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
            "model_type": row["model_type"],
            "developer": row["developer"],
            "num_speakers": row["num_speakers"],
            "sample_rate": row["sample_rate"],
            "runtime": row["runtime"],
            "provider": row["provider"],
            "engine_family": row["engine_family"],
            "distribution_channel": row["distribution_channel"],
            "capability_tags": capability_tags,
            "taxonomy_source": row["taxonomy_source"],
            "taxonomy_confidence": row["taxonomy_confidence"],
            "source_type": row["source_type"],
            "source_name": row["source_name"],
            "collected_at": row["collected_at"],
        }
        voices.append(voice)

        platforms[platform] += 1
        engines[row["engine"]] += 1
        genders[voice["gender"]] += 1
        runtimes[str(row["runtime"] or "Unknown")] += 1
        providers[str(row["provider"] or "Unknown")] += 1
        engine_families[str(row["engine_family"] or "unknown")] += 1
        distribution_channels[str(row["distribution_channel"] or "unknown")] += 1

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

    covered_country_codes = {
        (v.get("country_code") or "ZZ").upper()
        for v in voices
        if (v.get("country_code") or "ZZ").upper() in population_by_country
    }
    covered_online_codes = {
        (v.get("country_code") or "ZZ").upper()
        for v in voices
        if v.get("mode") == "online"
        and (v.get("country_code") or "ZZ").upper() in population_by_country
    }
    covered_offline_codes = {
        (v.get("country_code") or "ZZ").upper()
        for v in voices
        if v.get("mode") == "offline"
        and (v.get("country_code") or "ZZ").upper() in population_by_country
    }
    covered_language_qids: set[str] = set()
    online_language_qids: set[str] = set()
    offline_language_qids: set[str] = set()
    for v in voices:
        lang_codes = v.get("language_codes") or []
        if not isinstance(lang_codes, list):
            continue
        for raw_code in lang_codes:
            primary = normalize_primary_language_tag(str(raw_code or ""))
            if not primary:
                continue
            qid = None
            if len(primary) == 2 and primary in language_by_iso1:
                qid = language_by_iso1[primary][0]
            elif len(primary) == 3 and primary in language_by_iso3:
                qid = language_by_iso3[primary][0]
            if not qid:
                continue
            covered_language_qids.add(qid)
            if v.get("mode") == "online":
                online_language_qids.add(qid)
            else:
                offline_language_qids.add(qid)
    reference_languages_total = len(language_speakers_by_qid)
    reference_languages_covered = len(covered_language_qids)
    reference_languages_online_covered = len(online_language_qids)
    reference_languages_offline_covered = len(offline_language_qids)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "voices": len(voices),
            "platforms": dict(platforms),
            "engines": len(engines),
            "countries": len(countries),
            "online": sum(1 for v in voices if v["mode"] == "online"),
            "offline": sum(1 for v in voices if v["mode"] == "offline"),
            "world_population_total": total_world_population,
            "world_population_covered": sum(
                population_by_country[c] for c in covered_country_codes
            ),
            "world_population_online_covered": sum(
                population_by_country[c] for c in covered_online_codes
            ),
            "world_population_offline_covered": sum(
                population_by_country[c] for c in covered_offline_codes
            ),
            "language_speakers_total": total_language_speakers,
            "language_speakers_covered": sum(
                int(language_speakers_by_qid[q]["speakers"])
                for q in covered_language_qids
                if q in language_speakers_by_qid
            ),
            "language_speakers_online_covered": sum(
                int(language_speakers_by_qid[q]["speakers"])
                for q in online_language_qids
                if q in language_speakers_by_qid
            ),
            "language_speakers_offline_covered": sum(
                int(language_speakers_by_qid[q]["speakers"])
                for q in offline_language_qids
                if q in language_speakers_by_qid
            ),
            "reference_languages_total": reference_languages_total,
            "reference_languages_covered": reference_languages_covered,
            "reference_languages_online_covered": reference_languages_online_covered,
            "reference_languages_offline_covered": reference_languages_offline_covered,
            "reference_languages_no_tts": max(
                0, reference_languages_total - reference_languages_covered
            ),
            "reference_languages_no_online_tts": max(
                0, reference_languages_total - reference_languages_online_covered
            ),
            "reference_languages_no_offline_tts": max(
                0, reference_languages_total - reference_languages_offline_covered
            ),
        },
        "facets": {
            "platforms": dict(platforms),
            "engines": dict(engines),
            "genders": dict(genders),
            "runtimes": dict(runtimes),
            "providers": dict(providers),
            "engine_families": dict(engine_families),
            "distribution_channels": dict(distribution_channels),
        },
        "solutions": [
            {
                "id": row["id"],
                "name": row["name"],
                "category": row["category"],
                "vendor": row["vendor"],
                "platforms": parse_json_field(row["platforms"], []),
                "links": parse_json_field(row["links"], []),
            }
            for row in solution_meta
        ],
        "solution_matches": [
            {
                "solution_id": row["solution_id"],
                "category": row["category"],
                "support_level": row["support_level"],
                "voice_count": row["voice_count"],
            }
            for row in solution_rows
        ],
        "solution_runtime_support": [
            {
                "solution_id": row["solution_id"],
                "runtime": row["runtime"],
                "runtime_class": row["runtime_class"],
                "support_level": row["support_level"],
                "mode": row["mode"],
                "notes": row["notes"],
            }
            for row in solution_runtime_support
        ],
        "solution_provider_support": [
            {
                "solution_id": row["solution_id"],
                "provider": row["provider"],
                "support_level": row["support_level"],
                "mode": row["mode"],
                "notes": row["notes"],
            }
            for row in solution_provider_support
        ],
        "population_by_country": population_by_country,
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
