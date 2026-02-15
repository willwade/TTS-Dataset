#!/usr/bin/env python3
"""
Harmonize collected voice data into a SQLite database for Datasette.

This script:
1. Merges all JSON files from data/raw/
2. Enriches language + geo metadata
3. Merges preview URLs from reference data
4. Deduplicates by engine/platform/id
5. Outputs to data/voices.db with full-text search
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from langcodes import Language
except ImportError:
    print("Error: langcodes not installed.")
    print("Install with: pip install langcodes")
    sys.exit(1)


def parse_iso_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.min


def sanitize_lang_code(lang_code: str) -> str:
    code = str(lang_code).strip().replace("_", "-")
    # Some legacy sources include control characters or odd punctuation.
    return "".join(ch for ch in code if ch.isalnum() or ch == "-")


def load_geo_data(reference_dir: Path) -> dict[str, dict[str, Any]]:
    geo_path = reference_dir / "geo-data.json"
    if not geo_path.exists():
        return {}
    data = json.loads(geo_path.read_text(encoding="utf-8"))
    mapping: dict[str, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        language_id = item.get("language_id")
        if language_id:
            mapping[str(language_id)] = item
    return mapping


def load_preview_map(reference_dir: Path) -> dict[str, str]:
    """Load Azure preview URLs keyed by voice name."""
    preview_path = reference_dir / "azure_voice_previews.json"
    if not preview_path.exists():
        return {}
    data = json.loads(preview_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def load_acapela_preview_list(reference_dir: Path) -> list[dict[str, Any]]:
    """Load Acapela preview list from scraper output."""
    preview_path = reference_dir / "acapela_voice_previews.json"
    if not preview_path.exists():
        return []
    data = json.loads(preview_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def load_worldalphabets_audio_index(reference_dir: Path) -> list[dict[str, Any]]:
    index_path = reference_dir / "worldalphabets_audio_index.json"
    if not index_path.exists():
        return []
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def normalize_token(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def normalize_engine_name(engine: str) -> str:
    value = normalize_token(engine)
    if "microsoft" in value or "azure" in value:
        return "microsoft"
    if "polly" in value:
        return "polly"
    if "eleven" in value:
        return "elevenlabs"
    if "sherpa" in value:
        return "sherpaonnx"
    if "espeak" in value:
        return "espeak"
    if "watson" in value:
        return "watson"
    if "witai" in value or value.startswith("wit"):
        return "witai"
    if "uplift" in value:
        return "upliftai"
    if "openai" in value:
        return "openai"
    if "googletrans" in value:
        return "googletrans"
    if "google" in value:
        return "google"
    if "playht" in value:
        return "playht"
    return value


def canonical_platform(platform: str, engine: str) -> str:
    raw_engine = normalize_token(engine)
    local_hints = {
        "sapi",
        "uwp",
        "avsynth",
        "espeak",
        "rhvoice",
        "nuance",
        "acapela",
        "anreader",
        "cereproc",
    }
    if any(hint in raw_engine for hint in local_hints):
        return str(platform).strip().lower() or "unknown"

    engine_name = normalize_engine_name(engine)
    online_engines = {
        "google",
        "googletrans",
        "microsoft",
        "polly",
        "elevenlabs",
        "watson",
        "witai",
        "openai",
        "playht",
        "upliftai",
        "sherpaonnx",
    }
    if engine_name in online_engines:
        return "online"
    return str(platform).strip().lower() or "unknown"


def get_language_info(lang_code: str) -> dict[str, Any]:
    """Enrich language code with metadata from langcodes."""
    result = {"language_name": None, "language_display": None, "country_code": None, "script": None}
    if not lang_code or lang_code == "unknown":
        return result

    try:
        lang = Language.get(lang_code)
        if not lang:
            parts = lang_code.split("-")
            lang = Language.get(f"{parts[0]}-{parts[1]}") if len(parts) > 1 else Language.get(parts[0])

        if lang:
            result["language_name"] = (
                lang.language_name() if hasattr(lang, "language_name") else str(lang)
            )
            result["language_display"] = lang.display_name()
            result["script"] = lang.script if hasattr(lang, "script") else None
            if hasattr(lang, "territory") and lang.territory:
                result["country_code"] = lang.territory
            elif hasattr(lang, "maximize"):
                try:
                    maximized = lang.maximize()
                    result["country_code"] = (
                        maximized.territory if hasattr(maximized, "territory") else None
                    )
                except Exception:
                    pass
    except Exception as e:
        print(f"Warning: Could not get language info for {lang_code}: {e}")

    return result


def load_json_files(raw_dir: Path) -> list[dict[str, Any]]:
    """Load and merge all JSON files from data/raw/ recursively."""
    all_voices: list[dict[str, Any]] = []
    if not raw_dir.exists():
        print(f"Warning: Raw data directory not found: {raw_dir}")
        return []

    json_files = list(raw_dir.rglob("*.json"))
    print(f"Found {len(json_files)} JSON files in {raw_dir}")

    for json_file in json_files:
        print(f"Loading {json_file.name}...")
        text = json_file.read_text(encoding="utf-8")
        try:
            payloads = [json.loads(text)]
        except json.JSONDecodeError as e:
            # Fallback for accidental concatenated JSON payloads.
            decoder = json.JSONDecoder()
            payloads = []
            idx = 0
            length = len(text)
            while idx < length:
                while idx < length and text[idx].isspace():
                    idx += 1
                if idx >= length:
                    break
                try:
                    obj, next_idx = decoder.raw_decode(text, idx)
                except json.JSONDecodeError:
                    payloads = []
                    break
                payloads.append(obj)
                idx = next_idx
            if not payloads:
                print(f"Error parsing {json_file.name}: {e}")
                continue
            print(
                f"Warning: {json_file.name} had concatenated JSON payloads; "
                f"recovered {len(payloads)} block(s)"
            )

        for data in payloads:
            if not isinstance(data, list):
                print(f"Warning: {json_file.name} contains a non-list payload, skipping payload")
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                normalized = item.copy()
                normalized["platform"] = canonical_platform(
                    str(item.get("platform", "")),
                    str(item.get("engine", "")),
                )
                all_voices.append(normalized)
    return all_voices


def build_voice_key(voice: dict[str, Any]) -> str:
    engine = str(voice.get("engine", "")).strip().lower()
    platform = str(voice.get("platform", "")).strip().lower()
    voice_id = str(voice.get("id", "")).strip()
    return f"{engine}::{platform}::{voice_id}"


def deduplicate_voices(voices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by engine/platform/id and keep newest collected_at."""
    seen: dict[str, dict[str, Any]] = {}
    for voice in voices:
        if not voice.get("id"):
            continue
        key = build_voice_key(voice)
        if key not in seen:
            seen[key] = voice
            continue
        if parse_iso_datetime(voice.get("collected_at")) > parse_iso_datetime(
            seen[key].get("collected_at")
        ):
            seen[key] = voice
    deduped = list(seen.values())
    deduped.sort(key=lambda v: (str(v.get("platform", "")), str(v.get("engine", "")), str(v.get("name", ""))))
    return deduped


def enrich_voices(
    voices: list[dict[str, Any]],
    geo_map: dict[str, dict[str, Any]],
    preview_map: dict[str, str],
    acapela_previews: list[dict[str, Any]],
    worldalphabets_audio: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrich voices with language, geo, and preview metadata."""
    enriched: list[dict[str, Any]] = []
    acapela_by_name_lang: dict[tuple[str, str], dict[str, Any]] = {}
    for item in acapela_previews:
        name = str(item.get("name", "")).strip().lower()
        codes = item.get("language_codes", [])
        lang = str(codes[0]).strip().lower() if isinstance(codes, list) and codes else ""
        if name and lang:
            acapela_by_name_lang[(name, lang)] = item
    world_by_engine_voice: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in worldalphabets_audio:
        engine = normalize_engine_name(str(item.get("engine_norm", item.get("engine", ""))))
        voice_id = str(item.get("voice_id_norm", "")).strip().lower()
        key = (engine, voice_id)
        world_by_engine_voice.setdefault(key, []).append(item)

    for voice in voices:
        v = voice.copy()
        lang_codes = v.get("language_codes", [])
        primary_lang = ""
        if isinstance(lang_codes, list) and lang_codes:
            primary_lang = sanitize_lang_code(str(lang_codes[0]))
        elif isinstance(lang_codes, str):
            primary_lang = sanitize_lang_code(lang_codes)

        # language metadata
        lang_info = get_language_info(primary_lang) if primary_lang else {
            "language_name": None,
            "language_display": "Unknown",
            "country_code": None,
            "script": None,
        }
        v.update(lang_info)

        # geo metadata
        geo = geo_map.get(primary_lang, {})
        if not geo and primary_lang:
            geo = geo_map.get(primary_lang.replace("-", "_"), {})
        v["latitude"] = geo.get("latitude")
        v["longitude"] = geo.get("longitude")
        v["geo_country"] = geo.get("country")
        v["geo_region"] = geo.get("region")
        v["written_script"] = geo.get("written_script")

        # preview URL mapping (if not already present)
        if not v.get("preview_audio"):
            engine = str(v.get("engine", "")).lower()
            if "microsoft" in engine or "azure" in engine:
                mapped = preview_map.get(str(v.get("name", "")))
                if mapped:
                    v["preview_audio"] = mapped
            elif "acapela" in engine:
                key = (str(v.get("name", "")).strip().lower(), primary_lang.strip().lower())
                match = acapela_by_name_lang.get(key)
                if match:
                    if not v.get("preview_audio"):
                        v["preview_audio"] = match.get("preview_audio")
                    if not v.get("quality"):
                        v["quality"] = match.get("quality")

        # WorldAlphabets multi-preview enrichment
        engine_norm = normalize_engine_name(str(v.get("engine", "")))
        voice_norm = normalize_token(str(v.get("id", "")))
        wa_matches = world_by_engine_voice.get((engine_norm, voice_norm), [])
        previews: list[dict[str, str]] = []
        for match in wa_matches:
            url = str(match.get("url", "")).strip()
            if not url:
                continue
            previews.append(
                {
                    "url": url,
                    "language_code": str(match.get("language_code", "")).strip(),
                    "source": "worldalphabets",
                }
            )
        # Ensure existing single preview URL remains represented.
        if v.get("preview_audio"):
            previews.append(
                {
                    "url": str(v.get("preview_audio")),
                    "language_code": primary_lang,
                    "source": "existing",
                }
            )
        dedup_preview: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for item in previews:
            url = item["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            dedup_preview.append(item)
        if dedup_preview:
            v["preview_audios"] = dedup_preview
            # Keep legacy single URL field for backward compatibility.
            if not v.get("preview_audio"):
                v["preview_audio"] = dedup_preview[0]["url"]
        else:
            v["preview_audios"] = None

        # normalize styles to json text at DB write time
        if "styles" not in v:
            v["styles"] = None

        # provenance
        v["source_type"] = v.get("source_type", "runtime")
        v["source_name"] = v.get("source_name", "py3-tts-wrapper")

        enriched.append(v)

    return enriched


def create_database(db_path: Path, voices: list[dict[str, Any]]) -> None:
    """Create SQLite database with rich voice metadata + FTS."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS voices")
    cursor.execute("DROP TABLE IF EXISTS voices_fts")

    cursor.execute(
        """
        CREATE TABLE voices (
            voice_key TEXT PRIMARY KEY,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            language_codes TEXT NOT NULL,
            gender TEXT,
            engine TEXT NOT NULL,
            platform TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            language_name TEXT,
            language_display TEXT,
            country_code TEXT,
            script TEXT,
            latitude REAL,
            longitude REAL,
            geo_country TEXT,
            geo_region TEXT,
            written_script TEXT,
            preview_audio TEXT,
            preview_audios TEXT,
            quality TEXT,
            styles TEXT,
            software TEXT,
            age TEXT,
            source_type TEXT,
            source_name TEXT
        )
        """
    )

    for voice in voices:
        styles = voice.get("styles")
        styles_json = json.dumps(styles, ensure_ascii=False) if styles is not None else None
        preview_audios = voice.get("preview_audios")
        preview_audios_json = (
            json.dumps(preview_audios, ensure_ascii=False) if preview_audios is not None else None
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO voices (
                voice_key, id, name, language_codes, gender, engine, platform, collected_at,
                language_name, language_display, country_code, script,
                latitude, longitude, geo_country, geo_region, written_script,
                preview_audio, preview_audios, quality, styles, software, age, source_type, source_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                build_voice_key(voice),
                voice.get("id"),
                voice.get("name"),
                json.dumps(voice.get("language_codes", []), ensure_ascii=False),
                voice.get("gender"),
                voice.get("engine"),
                voice.get("platform"),
                voice.get("collected_at"),
                voice.get("language_name"),
                voice.get("language_display"),
                voice.get("country_code"),
                voice.get("script"),
                voice.get("latitude"),
                voice.get("longitude"),
                voice.get("geo_country"),
                voice.get("geo_region"),
                voice.get("written_script"),
                voice.get("preview_audio"),
                preview_audios_json,
                voice.get("quality"),
                styles_json,
                voice.get("software"),
                str(voice.get("age")) if voice.get("age") is not None else None,
                voice.get("source_type"),
                voice.get("source_name"),
            ),
        )

    cursor.execute(
        """
        CREATE VIRTUAL TABLE voices_fts
        USING fts5(name, language_name, language_display, engine, platform, software, quality)
        """
    )
    cursor.execute(
        """
        INSERT INTO voices_fts(rowid, name, language_name, language_display, engine, platform, software, quality)
        SELECT rowid, name, language_name, language_display, engine, platform, software, quality
        FROM voices
        """
    )

    cursor.execute("CREATE INDEX idx_voices_platform ON voices(platform)")
    cursor.execute("CREATE INDEX idx_voices_engine ON voices(engine)")
    cursor.execute("CREATE INDEX idx_voices_language_display ON voices(language_display)")
    cursor.execute("CREATE INDEX idx_voices_source_type ON voices(source_type)")

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM voices")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT platform) FROM voices")
    platforms = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT engine) FROM voices")
    engines = cursor.fetchone()[0]
    print(f"Database created: {total} voices from {platforms} platforms, {engines} engines")
    conn.close()


def main() -> None:
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    raw_dir = project_root / "data" / "raw"
    db_path = project_root / "data" / "voices.db"
    reference_dir = project_root / "data" / "reference"

    print("TTS Voice Harmonization")
    print("=" * 40)

    voices = load_json_files(raw_dir)
    if not voices:
        print("No voices to process. Exiting.")
        sys.exit(1)
    print(f"Loaded {len(voices)} total voices")

    voices = deduplicate_voices(voices)
    print(f"After deduplication: {len(voices)} unique voices")

    geo_map = load_geo_data(reference_dir)
    preview_map = load_preview_map(reference_dir)
    acapela_previews = load_acapela_preview_list(reference_dir)
    worldalphabets_audio = load_worldalphabets_audio_index(reference_dir)
    voices = enrich_voices(voices, geo_map, preview_map, acapela_previews, worldalphabets_audio)
    print("Enriched with language, geo, and preview metadata")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    create_database(db_path, voices)
    print(f"\nDatabase saved to: {db_path}")
    print("\nReady for Datasette deployment!")


if __name__ == "__main__":
    main()
