#!/usr/bin/env python3
"""
Harmonize collected voice data into a SQLite database for Datasette.

This script:
1. Merges all JSON files from data/raw/
2. Enriches voice data with langcodes metadata
3. Deduplicates voices by ID
4. Outputs to data/voices.db with full-text search
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

try:
    from langcodes import Language
except ImportError:
    print("Error: langcodes not installed.")
    print("Install with: pip install langcodes")
    sys.exit(1)


def get_language_info(lang_code: str) -> Dict[str, Any]:
    """
    Enrich language code with metadata from langcodes library.

    Returns dict with language_name, display_name, territory, script.
    """
    result = {"language_name": None, "language_display": None, "country_code": None, "script": None}

    if not lang_code or lang_code == "unknown":
        return result

    try:
        # Handle both BCP 47 tags (en-US) and ISO 639 codes (en)
        lang = Language.get(lang_code)
        if not lang:
            # Try parsing as locale
            parts = lang_code.split("-")
            if len(parts) > 1:
                lang = Language.get(f"{parts[0]}-{parts[1]}")
            else:
                lang = Language.get(parts[0])

        if lang:
            result["language_name"] = (
                lang.language_name() if hasattr(lang, "language_name") else str(lang)
            )
            result["language_display"] = lang.display_name()
            result["script"] = lang.script if hasattr(lang, "script") else None

            # Get territory/country code
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


def load_json_files(raw_dir: Path) -> List[Dict[str, Any]]:
    """
    Load and merge all JSON files from data/raw/.

    Returns a list of voice dictionaries.
    """
    all_voices = []
    raw_dir = Path(raw_dir)

    if not raw_dir.exists():
        print(f"Warning: Raw data directory not found: {raw_dir}")
        return []

    json_files = list(raw_dir.glob("*.json"))
    print(f"Found {len(json_files)} JSON files in {raw_dir}")

    for json_file in json_files:
        print(f"Loading {json_file.name}...")
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_voices.extend(data)
                else:
                    print(f"Warning: {json_file.name} does not contain a list, skipping")
        except json.JSONDecodeError as e:
            print(f"Error parsing {json_file.name}: {e}")

    return all_voices


def deduplicate_voices(voices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate voices by ID.

    When duplicates exist, keeps the most recently collected entry.
    """
    seen = {}
    deduped = []

    for voice in voices:
        voice_id = voice.get("id")
        if not voice_id:
            continue

        if voice_id in seen:
            # Keep the newer entry based on collected_at
            existing = seen[voice_id]
            existing_time = datetime.fromisoformat(existing.get("collected_at", ""))
            new_time = datetime.fromisoformat(voice.get("collected_at", ""))

            if new_time > existing_time:
                seen[voice_id] = voice
        else:
            seen[voice_id] = voice

    # Convert back to list and sort by platform, name
    deduped = list(seen.values())
    deduped.sort(key=lambda v: (v.get("platform", ""), v.get("name", "")))

    return deduped


def enrich_voices(voices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Enrich voice data with language metadata from langcodes.

    Adds fields: language_name, language_display, country_code, script
    """
    enriched = []

    for voice in voices:
        enriched_voice = voice.copy()

        # Get primary language code (first in list)
        lang_codes = voice.get("language_codes", [])
        if lang_codes:
            primary_lang = lang_codes[0] if isinstance(lang_codes, list) else lang_codes
            lang_info = get_language_info(primary_lang)

            enriched_voice.update(lang_info)
        else:
            enriched_voice.update(
                {
                    "language_name": None,
                    "language_display": "Unknown",
                    "country_code": None,
                    "script": None,
                }
            )

        enriched.append(enriched_voice)

    return enriched


def create_database(db_path: Path, voices: List[Dict[str, Any]]):
    """
    Create SQLite database with voices table and full-text search.

    Uses sqlite3 directly for better control.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create table with enriched fields
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS voices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            language_codes TEXT NOT NULL,
            gender TEXT,
            engine TEXT NOT NULL,
            platform TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            language_name TEXT,
            language_display TEXT,
            country_code TEXT,
            script TEXT
        )
    """)

    # Clear existing data (we rebuild each time)
    cursor.execute("DELETE FROM voices")

    # Insert all voices
    for voice in voices:
        cursor.execute(
            """
            INSERT OR REPLACE INTO voices (
                id, name, language_codes, gender, engine,
                platform, collected_at, language_name,
                language_display, country_code, script
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                voice.get("id"),
                voice.get("name"),
                json.dumps(voice.get("language_codes", [])),
                voice.get("gender"),
                voice.get("engine"),
                voice.get("platform"),
                voice.get("collected_at"),
                voice.get("language_name"),
                voice.get("language_display"),
                voice.get("country_code"),
                voice.get("script"),
            ),
        )

    # Create FTS table for full-text search
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS voices_fts
        USING fts5(name, language_name, language_display, engine, platform)
    """)

    # Populate FTS table
    cursor.execute("""
        INSERT INTO voices_fts(rowid, name, language_name, language_display, engine, platform)
        SELECT rowid, name, language_name, language_display, engine, platform
        FROM voices
    """)

    # Create index for faster queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_voices_platform
        ON voices(platform)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_voices_engine
        ON voices(engine)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_voices_language_display
        ON voices(language_display)
    """)

    conn.commit()

    # Print stats
    cursor.execute("SELECT COUNT(*) FROM voices")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT platform) FROM voices")
    platforms = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT engine) FROM voices")
    engines = cursor.fetchone()[0]

    print(f"Database created: {total} voices from {platforms} platforms, {engines} engines")

    conn.close()


def main():
    """Main entry point for harmonization."""
    # Determine paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    raw_dir = project_root / "data" / "raw"
    db_path = project_root / "data" / "voices.db"

    print("TTS Voice Harmonization")
    print("=" * 40)

    # Load all JSON files
    voices = load_json_files(raw_dir)
    if not voices:
        print("No voices to process. Exiting.")
        sys.exit(1)

    print(f"Loaded {len(voices)} total voices")

    # Deduplicate
    voices = deduplicate_voices(voices)
    print(f"After deduplication: {len(voices)} unique voices")

    # Enrich with language metadata
    voices = enrich_voices(voices)
    print("Enriched with language metadata")

    # Create database
    db_path.parent.mkdir(parents=True, exist_ok=True)
    create_database(db_path, voices)

    print(f"\nDatabase saved to: {db_path}")
    print("\nReady for Datasette deployment!")


if __name__ == "__main__":
    main()
