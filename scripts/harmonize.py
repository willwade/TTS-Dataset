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
import re
import sqlite3
import sys
from fnmatch import fnmatchcase
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from langcodes import Language
except ImportError:
    print("Error: langcodes not installed.")
    print("Install with: pip install langcodes")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("Error: pyyaml not installed.")
    print("Install with: pip install pyyaml")
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
    if raw_engine == "sherpaonnx":
        return "local"
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


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_taxonomy_map(reference_dir: Path) -> dict[str, Any]:
    path = reference_dir / "voice-taxonomy-map.yaml"
    data = load_yaml_file(path)
    return data if data else {}


def load_accessibility_solutions(reference_dir: Path) -> dict[str, Any]:
    path = reference_dir / "accessibility-solutions.yaml"
    data = load_yaml_file(path)
    return data if data else {"solutions": []}


def normalize_support_level(value: Any) -> str:
    text = str(value or "").strip().lower()
    allowed = {"native", "compatible", "possible", "unsupported", "unknown"}
    return text if text in allowed else "unknown"


def normalize_runtime_class(value: Any, runtime: str = "") -> str:
    text = str(value or "").strip().lower()
    if text in {"direct", "broker"}:
        return text
    runtime_norm = normalize_token(runtime)
    if runtime_norm in {"speechdispatcher", "browserspeechsynthesiswebspeechapi", "webspeechapi"}:
        return "broker"
    return "direct"


def normalize_provider_name(value: str) -> str:
    token = normalize_token(value)
    provider_map = {
        "mms": "Meta",
        "meta": "Meta",
        "piper": "Piper",
        "coqui": "Coqui",
        "kokoro": "Kokoro",
        "k2fsa": "k2-fsa",
        "icefall": "k2-fsa",
        "mimic3": "Mimic3",
        "melotts": "MeloTTS",
    }
    if token in provider_map:
        return provider_map[token]
    return str(value or "").strip() or "Unknown"


def normalize_engine_family(value: str) -> str:
    token = normalize_token(value)
    family_map = {
        "mms": "mms-tts",
        "mmstts": "mms-tts",
        "coqui": "coqui-tts",
        "piper": "piper",
        "vits": "vits",
        "matcha": "matcha",
        "kokoro": "kokoro",
    }
    return family_map.get(token, str(value or "").strip().lower() or "unknown")


def as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _rule_match_engine(rule_engine: Any, engine: str) -> bool:
    if not rule_engine:
        return True
    return normalize_token(str(rule_engine)) == normalize_token(engine)


def _rule_match_id_glob(rule_id: Any, voice_id: str) -> bool:
    if not rule_id:
        return True
    return fnmatchcase(str(voice_id).lower(), str(rule_id).lower())


def _best_support_level(*levels: str) -> str:
    rank = {"native": 5, "compatible": 4, "possible": 3, "unknown": 2, "unsupported": 1}
    normalized = [normalize_support_level(level) for level in levels if level]
    if not normalized:
        return "unknown"
    return max(normalized, key=lambda x: rank.get(x, 0))


def apply_voice_taxonomy(voice: dict[str, Any], taxonomy: dict[str, Any]) -> dict[str, Any]:
    defaults = taxonomy.get("defaults", {})
    out = {
        "runtime": str(defaults.get("runtime", "Unknown")),
        "provider": str(defaults.get("provider", "Unknown")),
        "engine_family": str(defaults.get("engine_family", "unknown")),
        "distribution_channel": str(defaults.get("distribution_channel", "online_api")),
        "capability_tags": as_string_list(defaults.get("capability_tags", [])),
        "taxonomy_source": str(defaults.get("taxonomy_source", "heuristic")),
        "taxonomy_confidence": str(defaults.get("taxonomy_confidence", "low")),
    }
    voice_key = build_voice_key(voice)
    voice_id = str(voice.get("id", ""))
    engine = str(voice.get("engine", ""))
    voice_name = str(voice.get("name", ""))

    # Preferred Sherpa mapping from runtime metadata when available.
    if normalize_token(engine) == "sherpaonnx":
        developer = str(voice.get("developer", "")).strip()
        model_type = str(voice.get("model_type", "")).strip()
        if developer:
            out["provider"] = normalize_provider_name(developer)
            out["taxonomy_source"] = "heuristic"
            out["taxonomy_confidence"] = "medium"
        if model_type:
            out["engine_family"] = normalize_engine_family(model_type)
            out["taxonomy_source"] = "heuristic"
            out["taxonomy_confidence"] = "medium"

    # 1) Exact voice_key
    for rule in taxonomy.get("voice_key_exact", []):
        if not isinstance(rule, dict):
            continue
        if str(rule.get("voice_key", "")).lower() != voice_key.lower():
            continue
        for k in out:
            if k in rule:
                out[k] = as_string_list(rule[k]) if k == "capability_tags" else rule[k]
        return out

    # 2) Engine + ID exact/glob
    for rule in taxonomy.get("engine_id_exact", []):
        if not isinstance(rule, dict):
            continue
        if not _rule_match_engine(rule.get("engine"), engine):
            continue
        if not _rule_match_id_glob(rule.get("id"), voice_id):
            continue
        for k in out:
            if k in rule:
                out[k] = as_string_list(rule[k]) if k == "capability_tags" else rule[k]
        return out

    # 3) id_or_name_pattern
    for rule in taxonomy.get("id_or_name_pattern", []):
        if not isinstance(rule, dict):
            continue
        when = rule.get("when", {})
        if not isinstance(when, dict):
            continue
        if not _rule_match_engine(when.get("engine"), engine):
            continue
        id_regex = str(when.get("id_regex", "")).strip()
        name_regex = str(when.get("name_regex", "")).strip()
        id_match = bool(id_regex) and bool(re.search(id_regex, voice_id))
        name_match = bool(name_regex) and bool(re.search(name_regex, voice_name))
        if not (id_match or name_match):
            continue
        updates = rule.get("set", {})
        if not isinstance(updates, dict):
            continue
        for k in out:
            if k in updates:
                out[k] = as_string_list(updates[k]) if k == "capability_tags" else updates[k]
        return out

    # 4) Engine default
    for rule in taxonomy.get("engine_default", []):
        if not isinstance(rule, dict):
            continue
        if not _rule_match_engine(rule.get("engine"), engine):
            continue
        for k in out:
            if k in rule:
                out[k] = as_string_list(rule[k]) if k == "capability_tags" else rule[k]
        return out

    return out


def derive_use_case_rows(voice: dict[str, Any], taxonomy: dict[str, Any]) -> list[dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    runtime = str(voice.get("runtime", ""))
    tags = set(voice.get("capability_tags", []) if isinstance(voice.get("capability_tags"), list) else [])
    for profile in taxonomy.get("use_case_profiles", []):
        if not isinstance(profile, dict):
            continue
        if normalize_token(profile.get("runtime")) != normalize_token(runtime):
            continue
        use_case = str(profile.get("use_case", "")).strip()
        if not use_case:
            continue
        rows[use_case] = {
            "use_case_id": use_case,
            "support_level": normalize_support_level(profile.get("support_level")),
            "notes": str(profile.get("notes", "")).strip(),
            "source": "taxonomy_profile",
        }

    tag_map = {
        "screenreadercompatible": "screenreader",
        "aaccompatible": "aac",
    }
    for tag in tags:
        tag_norm = normalize_token(tag)
        if tag_norm not in tag_map:
            continue
        use_case = tag_map[tag_norm]
        existing = rows.get(use_case)
        level = "compatible"
        if existing:
            existing["support_level"] = _best_support_level(existing["support_level"], level)
            if not existing.get("notes"):
                existing["notes"] = "Derived from capability tags"
            existing["source"] = "taxonomy_profile+tags"
        else:
            rows[use_case] = {
                "use_case_id": use_case,
                "support_level": level,
                "notes": "Derived from capability tags",
                "source": "capability_tags",
            }

    return list(rows.values())


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
    taxonomy: dict[str, Any],
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

        taxonomy_fields = apply_voice_taxonomy(v, taxonomy)
        v.update(taxonomy_fields)
        v["use_cases"] = derive_use_case_rows(v, taxonomy)

        enriched.append(v)

    return enriched


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _derive_solution_voice_matches(
    voices: list[dict[str, Any]], solutions_payload: dict[str, Any]
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    solutions = solutions_payload.get("solutions", [])
    if not isinstance(solutions, list):
        return out
    for solution in solutions:
        if not isinstance(solution, dict):
            continue
        solution_id = str(solution.get("id", "")).strip()
        category = str(solution.get("category", "")).strip().lower()
        if not solution_id:
            continue

        runtime_rules = solution.get("runtime_support", [])
        provider_rules = solution.get("provider_sdk_support", [])
        if not isinstance(runtime_rules, list):
            runtime_rules = []
        if not isinstance(provider_rules, list):
            provider_rules = []

        runtime_map = {
            normalize_token(item.get("runtime")): normalize_support_level(item.get("support_level"))
            for item in runtime_rules
            if isinstance(item, dict) and item.get("runtime")
        }
        provider_map = {
            normalize_token(item.get("provider")): normalize_support_level(item.get("support_level"))
            for item in provider_rules
            if isinstance(item, dict) and item.get("provider")
        }

        for voice in voices:
            voice_key = build_voice_key(voice)
            runtime_token = normalize_token(voice.get("runtime"))
            provider_token = normalize_token(voice.get("provider"))
            runtime_level = runtime_map.get(runtime_token)
            provider_level = provider_map.get(provider_token)
            if not runtime_level and not provider_level:
                continue
            support_level = _best_support_level(runtime_level or "", provider_level or "")
            if support_level in {"unknown", "unsupported"}:
                continue
            reason = (
                "both"
                if runtime_level and provider_level
                else "runtime_match"
                if runtime_level
                else "provider_match"
            )
            out.append(
                {
                    "solution_id": solution_id,
                    "voice_key": voice_key,
                    "support_level": support_level,
                    "reason": reason,
                    "category": category,
                }
            )
    return out


def create_database(
    db_path: Path, voices: list[dict[str, Any]], solutions_payload: dict[str, Any]
) -> None:
    """Create SQLite database with rich voice metadata + FTS."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS voices")
    cursor.execute("DROP TABLE IF EXISTS voices_fts")
    cursor.execute("DROP TABLE IF EXISTS voice_use_cases")
    cursor.execute("DROP TABLE IF EXISTS use_cases")
    cursor.execute("DROP TABLE IF EXISTS solution_voice_matches")
    cursor.execute("DROP TABLE IF EXISTS solution_provider_support")
    cursor.execute("DROP TABLE IF EXISTS solution_runtime_support")
    cursor.execute("DROP TABLE IF EXISTS solutions")

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
            model_type TEXT,
            developer TEXT,
            num_speakers INTEGER,
            sample_rate INTEGER,
            runtime TEXT,
            provider TEXT,
            engine_family TEXT,
            distribution_channel TEXT,
            capability_tags TEXT,
            taxonomy_source TEXT,
            taxonomy_confidence TEXT,
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
                preview_audio, preview_audios, quality, styles, software, age,
                model_type, developer, num_speakers, sample_rate,
                runtime, provider, engine_family, distribution_channel, capability_tags,
                taxonomy_source, taxonomy_confidence,
                source_type, source_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                voice.get("model_type"),
                voice.get("developer"),
                int(voice.get("num_speakers")) if voice.get("num_speakers") is not None else None,
                int(voice.get("sample_rate")) if voice.get("sample_rate") is not None else None,
                voice.get("runtime"),
                voice.get("provider"),
                voice.get("engine_family"),
                voice.get("distribution_channel"),
                _json_text(voice.get("capability_tags")),
                voice.get("taxonomy_source"),
                voice.get("taxonomy_confidence"),
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
    cursor.execute("CREATE INDEX idx_voices_runtime ON voices(runtime)")
    cursor.execute("CREATE INDEX idx_voices_provider ON voices(provider)")
    cursor.execute("CREATE INDEX idx_voices_engine_family ON voices(engine_family)")
    cursor.execute("CREATE INDEX idx_voices_distribution_channel ON voices(distribution_channel)")

    cursor.execute(
        """
        CREATE TABLE use_cases (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT
        )
        """
    )
    use_case_seed = {
        "screenreader": ("Screenreader", "Voice usable in screenreader workflows"),
        "aac": ("AAC", "Voice usable in augmentative communication workflows"),
    }
    for use_case_id, (name, description) in use_case_seed.items():
        cursor.execute(
            "INSERT OR REPLACE INTO use_cases (id, name, description) VALUES (?, ?, ?)",
            (use_case_id, name, description),
        )

    cursor.execute(
        """
        CREATE TABLE voice_use_cases (
            voice_key TEXT NOT NULL,
            use_case_id TEXT NOT NULL,
            support_level TEXT NOT NULL CHECK (support_level IN ('native','compatible','possible','unsupported','unknown')),
            notes TEXT,
            source TEXT,
            PRIMARY KEY (voice_key, use_case_id)
        )
        """
    )
    for voice in voices:
        voice_key = build_voice_key(voice)
        use_cases = voice.get("use_cases", [])
        if not isinstance(use_cases, list):
            continue
        for row in use_cases:
            if not isinstance(row, dict):
                continue
            use_case_id = str(row.get("use_case_id", "")).strip().lower()
            if use_case_id not in use_case_seed:
                continue
            cursor.execute(
                """
                INSERT OR REPLACE INTO voice_use_cases
                (voice_key, use_case_id, support_level, notes, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    voice_key,
                    use_case_id,
                    normalize_support_level(row.get("support_level")),
                    str(row.get("notes", ""))[:500] or None,
                    str(row.get("source", ""))[:100] or None,
                ),
            )

    cursor.execute(
        """
        CREATE TABLE solutions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL CHECK (category IN ('screenreader','aac')),
            vendor TEXT,
            platforms TEXT,
            links TEXT,
            source TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE solution_runtime_support (
            solution_id TEXT NOT NULL,
            runtime TEXT NOT NULL,
            runtime_class TEXT NOT NULL CHECK (runtime_class IN ('direct','broker')),
            support_level TEXT NOT NULL CHECK (support_level IN ('native','compatible','possible','unsupported','unknown')),
            mode TEXT,
            notes TEXT,
            PRIMARY KEY (solution_id, runtime)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE solution_provider_support (
            solution_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            support_level TEXT NOT NULL CHECK (support_level IN ('native','compatible','possible','unsupported','unknown')),
            mode TEXT,
            notes TEXT,
            PRIMARY KEY (solution_id, provider)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE solution_voice_matches (
            solution_id TEXT NOT NULL,
            voice_key TEXT NOT NULL,
            support_level TEXT NOT NULL CHECK (support_level IN ('native','compatible','possible','unsupported','unknown')),
            reason TEXT NOT NULL,
            category TEXT NOT NULL,
            PRIMARY KEY (solution_id, voice_key)
        )
        """
    )

    solutions = solutions_payload.get("solutions", [])
    if not isinstance(solutions, list):
        solutions = []
    for solution in solutions:
        if not isinstance(solution, dict):
            continue
        solution_id = str(solution.get("id", "")).strip()
        if not solution_id:
            continue
        category = str(solution.get("category", "")).strip().lower()
        if category not in {"screenreader", "aac"}:
            continue
        cursor.execute(
            """
            INSERT OR REPLACE INTO solutions (id, name, category, vendor, platforms, links, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                solution_id,
                str(solution.get("name", "")).strip() or solution_id,
                category,
                str(solution.get("vendor", "")).strip() or None,
                _json_text(solution.get("platforms", [])),
                _json_text(solution.get("links", [])),
                "accessibility-solutions.yaml",
            ),
        )
        runtime_support = solution.get("runtime_support", [])
        if isinstance(runtime_support, list):
            for item in runtime_support:
                if not isinstance(item, dict):
                    continue
                runtime = str(item.get("runtime", "")).strip()
                if not runtime:
                    continue
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO solution_runtime_support
                    (solution_id, runtime, runtime_class, support_level, mode, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        solution_id,
                        runtime,
                        normalize_runtime_class(item.get("runtime_class"), runtime),
                        normalize_support_level(item.get("support_level")),
                        str(item.get("mode", "")).strip() or None,
                        str(item.get("notes", "")).strip() or None,
                    ),
                )
        provider_support = solution.get("provider_sdk_support", [])
        if isinstance(provider_support, list):
            for item in provider_support:
                if not isinstance(item, dict):
                    continue
                provider = str(item.get("provider", "")).strip()
                if not provider:
                    continue
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO solution_provider_support
                    (solution_id, provider, support_level, mode, notes)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        solution_id,
                        provider,
                        normalize_support_level(item.get("support_level")),
                        str(item.get("mode", "")).strip() or None,
                        str(item.get("notes", "")).strip() or None,
                    ),
                )

    for match in _derive_solution_voice_matches(voices, solutions_payload):
        cursor.execute(
            """
            INSERT OR REPLACE INTO solution_voice_matches
            (solution_id, voice_key, support_level, reason, category)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                match["solution_id"],
                match["voice_key"],
                match["support_level"],
                match["reason"],
                match["category"],
            ),
        )

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
    taxonomy_map = load_taxonomy_map(reference_dir)
    accessibility_solutions = load_accessibility_solutions(reference_dir)
    voices = enrich_voices(
        voices,
        geo_map,
        preview_map,
        acapela_previews,
        worldalphabets_audio,
        taxonomy_map,
    )
    print("Enriched with language, geo, preview, and taxonomy metadata")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    create_database(db_path, voices, accessibility_solutions)
    print(f"\nDatabase saved to: {db_path}")
    print("\nReady for Datasette deployment!")


if __name__ == "__main__":
    main()
