# AGENTS.md

Guidance for coding agents working in `TTS-Dataset`.

## Scope

- Repository: `C:\github\TTS-Dataset`
- Canonical remote: `https://github.com/willwade/TTS-Dataset/`
- Primary goal: maintain a reproducible TTS voice dataset pipeline and static explorer.

## Core Commands

- Install/update env: `uv sync`
- Collect local platform voices: `uv run python scripts/collect_voices.py`
- Collect online engines: `uv run python scripts/collect_voices.py --online`
- Build DB: `uv run python scripts/harmonize.py`
- Export site payload: `uv run python scripts/export_site_data.py`
- Sync site payload: `node site/scripts/sync-data.mjs`
- Build site: `cd site && npm run build`
- Lint: `uv run --extra dev ruff check .`

## Data Safety Rules

- Do not reduce dataset quality silently.
- If a new collection produces fewer rows than existing raw JSON, keep the larger existing file.
- Preserve static curated files in `data/raw/` and `data/reference/`.
- Avoid destructive git commands (`reset --hard`, checkout overwrite) unless explicitly requested.

## Schema and Taxonomy Rules

- `voices` keeps legacy fields (`engine`, `platform`) for compatibility.
- Normalized taxonomy fields must remain populated:
  - `runtime`, `provider`, `engine_family`, `distribution_channel`
  - `capability_tags`, `taxonomy_source`, `taxonomy_confidence`
- Accessibility compatibility comes from:
  - `data/reference/accessibility-solutions.yaml`
- Broker runtime layers must use `runtime_class: broker` (for example `Speech Dispatcher`, browser speech).

## Sherpa-ONNX Rules

- Treat Sherpa-ONNX as runtime, not provider.
- Prefer runtime metadata from wrapper (`developer`, `model_type`).
- Use ID-prefix fallback mapping only when metadata is missing.

## Validation Before Finishing

Run these after data/model changes:

1. `uv run python scripts/harmonize.py`
2. `uv run python scripts/export_site_data.py`
3. `node site/scripts/sync-data.mjs`
4. `cd site && npm run build`
5. `uv run --extra dev ruff check .`

If any step fails, report it clearly and do not claim full completion.
