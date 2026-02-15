# TTS Voice Catalog Dataset

A monthly-updated dataset of Text-to-Speech voices collected from multiple sources using `py3-tts-wrapper`. Data is published to Datasette for browsable exploration and API access.

## Overview

This project automatically collects platform TTS voice information:

| Category | Sources | Voices Source |
|----------|---------|---------------|
| **Platform Engines** | Windows SAPI5 (+ UWP best-effort), macOS AVSynth + eSpeak, Linux eSpeak | Native/system TTS APIs |
| **Online Engines (optional)** | Google, Microsoft, Polly, ElevenLabs, Watson, Wit.ai, OpenAI, PlayHT, GoogleTrans, Sherpa-ONNX, UpliftAI | API/SDK voice catalogs |
| **Static/Legacy Datasets** | Acapela, Nuance, CereProc, RHVoice, ANReader, AVSynth, eSpeak, SAPI snapshots | Curated JSON snapshots |

## Data Pipeline

```
GitHub Actions (Monthly)
        ↓
py3-tts-wrapper get_voices()
        ↓
data/raw/{platform}-voices.json
        ↓
data/reference/*.json (geo + preview maps)
        ↓
scripts/harmonize.py (merge + enrich)
        ↓
data/voices.db (SQLite with FTS)
        ↓
Datasette on Vercel
```

## Quick Start

### Prerequisites

- Python 3.10+
- [UV](https://github.com/astral-sh/uv) package manager

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/TTS-Dataset.git
cd TTS-Dataset

# Install dependencies with UV
uv sync
```

### Local Usage

```bash
# Auto-detect platform and collect voices
uv run python scripts/collect_voices.py

# Collect online/credentialed engines (plus Sherpa-ONNX) and write per-engine JSON files
uv run python scripts/collect_voices.py --online

# List available local engines
uv run python scripts/collect_voices.py --list

# List all client engines exposed by py3-tts-wrapper
uv run python scripts/collect_voices.py --list-all

# Merge and enrich data, build SQLite database
uv run python scripts/harmonize.py

# Refresh preview reference data (best effort)
uv run python scripts/fetch_voice_previews.py

# Serve locally with Datasette
pip install datasette
datasette serve data/voices.db
```

## Environment Variables

Create `.env` from `.env.example` and configure:

| Variable | Required | Description |
|----------|-------------|
| `VERCEL_TOKEN` | Token for deploying to Vercel-hosted Datasette |

### Optional (for online engine collection)
| Variable | Service |
|----------|----------|
| `GOOGLE_TTS_CREDENTIALS` | Google Cloud TTS (path to JSON file) |
| `AZURE_TTS_KEY`, `AZURE_TTS_REGION` | Microsoft Azure TTS |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | AWS Polly |
| `ELEVENLABS_API_KEY` | ElevenLabs |
| `WATSON_API_KEY`, `WATSON_REGION` | IBM Watson |
| `WITAI_TOKEN` | Wit.AI |

Note: the GitHub Actions workflow collects platform engines on all OSes and additionally runs `--online` on Linux when credentials are configured.

Note: when a fresh collection returns fewer voices than an existing JSON file, the existing file is kept to avoid data loss from transient runner or API conditions.

### Legacy (optional)
| Variable | Description |
|----------|-------------|
| `GOOGLE_GEOCODE_KEY` | Google Maps geocoding (legacy) |

## Data Schema

### Raw JSON Format

```json
{
  "id": "voice-identifier",
  "name": "Voice Display Name",
  "language_codes": ["en-US", "eng"],
  "gender": "Male|Female|Unknown",
  "engine": "SAPI5|UWP|AVSynth|eSpeak|...",
  "platform": "windows|macos|linux",
  "collected_at": "2025-02-14T12:00:00Z",
  "preview_audio": "https://...",
  "quality": "High",
  "styles": ["chat", "newscast"],
  "software": "Vendor runtime/version",
  "age": "Adult",
  "source_type": "runtime|static",
  "source_name": "py3-tts-wrapper|static-file-name"
}
```

### SQLite Schema (Datasette)

| Column | Type | Description |
|---------|------|-------------|
| `voice_key` | TEXT | Primary key (`engine::platform::id`) |
| `id` | TEXT | Voice identifier |
| `name` | TEXT | Voice display name |
| `language_codes` | TEXT | JSON array of locale/ISO codes |
| `gender` | TEXT | Voice gender (if available) |
| `engine` | TEXT | TTS engine name |
| `platform` | TEXT | Source platform |
| `collected_at` | TEXT | ISO 8601 timestamp |
| `language_name` | TEXT | Enriched: English language name |
| `language_display` | TEXT | Enriched: Display language name |
| `country_code` | TEXT | Enriched: ISO 3166-1 alpha-2 |
| `script` | TEXT | Enriched: ISO 15924 script code |
| `latitude` | REAL | Enriched: language geolocation latitude |
| `longitude` | REAL | Enriched: language geolocation longitude |
| `geo_country` | TEXT | Enriched: geo country from reference map |
| `geo_region` | TEXT | Enriched: geo region from reference map |
| `written_script` | TEXT | Enriched: script from geo reference |
| `preview_audio` | TEXT | Preview audio URL (if known) |
| `quality` | TEXT | Vendor/voice quality label |
| `styles` | TEXT | JSON array of style tags |
| `software` | TEXT | Vendor software/runtime tag |
| `age` | TEXT | Voice age metadata |
| `source_type` | TEXT | `runtime` or `static` |
| `source_name` | TEXT | Source file/provider descriptor |

## Project Structure

```
TTS-Dataset/
├── .github/
│   └── workflows/
│       └── update-voices.yml    # Monthly automation
├── data/
│   ├── raw/                        # Collected + static JSON outputs (git-tracked)
│   ├── reference/                  # Geo + preview enrichment maps
│   └── voices.db                  # Build artifact (not in git)
├── scripts/
│   ├── collect_voices.py            # Simplified voice collection
│   ├── fetch_voice_previews.py      # Preview URL refresh (best effort)
│   ├── import_legacy_temp_data.py   # Static legacy import helper
│   └── harmonize.py                # Database build
├── tests/                           # Unit tests
├── pyproject.toml                   # UV config
├── .env.example                      # Environment template
├── .gitignore                       # Exclude .env, *.db
└── README.md
```

## GitHub Actions

The workflow runs monthly on first day of each month:

1. **Collect**: Matrix build on Windows/macOS/Linux runners
2. **Harmonize**: Merge JSON, enrich with language + geo + preview metadata
3. **Build**: Create SQLite database with full-text search
4. **Deploy**: Publish to Datasette on Vercel

Manual trigger available via Actions tab.
