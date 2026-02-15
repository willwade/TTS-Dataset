# Voice Taxonomy

This document defines the normalized taxonomy for `TTS-Dataset`.

## Why

Current `engine` mixes different concepts:
- runtime/API (e.g. `SAPI5`, `AVSynth`, `Sherpa-ONNX`)
- provider/vendor (e.g. `Nuance`, `Acapela`, `Microsoft`)
- model family (e.g. `Piper`)

The new taxonomy separates these concerns so filtering and analysis are correct.

## Canonical Fields

### `runtime`
Execution/runtime interface used to access or synthesize the voice.

Examples:
- `SAPI5`
- `AVSynth`
- `eSpeak`
- `Sherpa-ONNX`
- `Azure Speech API`
- `AWS Polly API`
- `IBM Watson TTS API`
- `GoogleTrans API`

### `provider`
Voice vendor/brand/provider.

Examples:
- `Microsoft`
- `Apple`
- `Nuance`
- `Acapela`
- `CereProc`
- `Piper`
- `RHVoice`
- `IBM`
- `Amazon`

### `engine_family`
Model/engine lineage for synthesis.

Examples:
- `unit-selection`
- `neural`
- `vits`
- `piper`
- `formant`
- `hybrid`
- `unknown`

### `distribution_channel`
How the voice is delivered in this dataset.

Allowed values:
- `platform_local`
- `platform_system`
- `online_api`
- `static_legacy`

### `capability_tags` (JSON array)
Cross-cutting capabilities and use-case labels.

Examples:
- `offline`
- `screenreader-compatible`
- `aac-compatible`
- `cloud-required`
- `sdk-required`

### `taxonomy_source`
Where mapping came from:
- `manual`
- `heuristic`

### `taxonomy_confidence`
- `high`
- `medium`
- `low`

## Precedence Rules

When mapping a voice, apply in this order:
1. Exact `voice_key` match
2. Exact `(engine, id)` match
3. Pattern match on `id` or `name`
4. Fallback by `engine`
5. Final fallback to `Unknown` provider/family with low confidence

## Use Cases

Use cases are many-to-many and should not be hard-coded into `provider` or `runtime`.

Initial use cases:
- `screenreader`
- `aac`

`voice_use_cases.support_level` values:
- `native`
- `compatible`
- `possible`
- `unsupported`
- `unknown`

### Handcrafted Solution Data Source

Maintain product-level compatibility in:
- `data/reference/accessibility-solutions.yaml`

This file captures:
- solution metadata (`id`, `name`, `category`, `vendor`, platforms)
- runtime compatibility (`runtime_support`)
- official provider SDK compatibility (`provider_sdk_support`)
- runtime class (`runtime_class`: `direct` or `broker`) for each runtime support row

Use this as the authoritative source for screenreader/AAC product claims.
Voice-level derived tags should be generated from this matrix, not hardcoded directly in voice records.

Modeling guidance:
- Treat broker layers such as `Speech Dispatcher` and `Browser Speech Synthesis (Web Speech API)` as runtimes.
- Do not create separate solution entries for broker runtimes themselves.
- Keep solution scope at software products/platforms rather than every hardware device SKU.

## Sherpa-ONNX Model Family Mapping

Sherpa-ONNX is a runtime wrapper for multiple model families. Do not treat all Sherpa voices as one provider.

Preferred mapping source:
- `developer` and `model_type` metadata returned by `py3-tts-wrapper`

Fallback mapping from `id` prefix:
- `mms_*` -> provider `Meta`, family `mms-tts`
- `piper_*` -> provider `Piper`, family `piper`
- `coqui_*` -> provider `Coqui`, family `coqui-tts`
- `vits_*` -> provider `Unknown`, family `vits`

Fallback for unmatched Sherpa IDs:
- provider `Unknown`
- family `unknown`
- confidence `low`

Current dataset snapshot (2026-02-15): Sherpa IDs are dominated by `mms_*`, so rules must be prefix-driven and re-evaluated regularly.

Full Sherpa model index snapshot from `tts-wrapper` (2026-02-15) includes additional families:
- `mms` (1143)
- `piper` (126)
- `coqui` (25)
- `zh` (14)
- `mimic3` (13)
- `icefall` (5)
- `kokoro` (3)
- plus smaller families (`tts`, `melo`, `cantonese`, etc.)

If collection returns only `mms_*`, it usually indicates the runtime wrapper is filtering voices instead of exposing all model entries.
