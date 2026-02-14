# TTS Voice Catalog Dataset

A monthly-updated dataset of Text-to-Speech voices collected from multiple sources using `py3-tts-wrapper`. Data is published to Datasette for browsable exploration and API access.

## Overview

This project automatically collects TTS voice information from three sources:

| Category | Sources | Voices Source |
|----------|---------|---------------|
| **Platform Engines** | Windows SAPI5, macOS NSSS, Linux eSpeak | Native system TTS APIs |
| **Online Engines** | Google, Azure, AWS Polly, ElevenLabs, Watson | Cloud TTS services |
| **Local Models** | Sherpa-ONNX (MMS, Piper) | Offline ONNX models |

## Data Pipeline

```
GitHub Actions (Monthly)
        ↓
py3-tts-wrapper get_voices()
        ↓
data/raw/{platform}-voices.json
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
uv pip install py3-tts-wrapper[sapi] sqlite-utils langcodes

# Optional: Install specific online engine dependencies
uv pip install -e ".[google]" py3-tts-wrapper[google]      # Google Cloud TTS
uv pip install -e ".[azure]" py3-tts-wrapper[microsoft]    # Microsoft Azure
uv pip install -e ".[aws-polly]" py3-tts-wrapper[polly]      # AWS Polly
uv pip install -e ".[elevenlabs]" py3-tts-wrapper[elevenlabs]  # ElevenLabs
uv pip install -e ".[watson]" py3-tts-wrapper[watson]      # IBM Watson
uv pip install -e ".[witai]" py3-tts-wrapper[witai]      # Wit.AI
```

### Local Usage

```bash
# Auto-detect platform and collect voices
uv run python scripts/collect_voices.py

# Collect from all available sources
uv run python scripts/collect_voices.py --all

# Collect from specific sources
python scripts/collect_voices.py sapi google azure sherpa

# Merge and enrich data, build SQLite database
uv run python scripts/harmonize.py

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
  "platform": "windows|macos|linux",
  "collected_at": "2025-02-14T12:00:00Z"
}
```

### SQLite Schema (Datasette)

| Column | Type | Description |
|---------|------|-------------|
| `id` | TEXT | Primary key (voice identifier) |
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

## Project Structure

```
TTS-Dataset/
├── .github/
│   └── workflows/
│       └── update-voices.yml    # Monthly automation
├── data/
│   ├── raw/                        # JSON outputs (git-tracked)
│   └── voices.db                  # Build artifact (not in git)
├── scripts/
│   ├── collect_voices.py            # Simplified voice collection
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
2. **Harmonize**: Merge JSON, enrich with langcodes metadata
3. **Build**: Create SQLite database with full-text search
4. **Deploy**: Publish to Datasette on Vercel

Manual trigger available via Actions tab.
