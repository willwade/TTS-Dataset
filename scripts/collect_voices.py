#!/usr/bin/env python3
"""
Simple TTS voice collection using py3-tts-wrapper.

Collects voices from:
- Windows: SAPI5
- macOS: AVSynth and eSpeak
- Linux: eSpeak

Output: data/raw/{platform}-voices.json
"""

import json
import inspect
import os
import platform
import sys
from base64 import b64decode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))


def detect_platform() -> str:
    """Detect the current platform for voice collection."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "macos"
    elif system == "linux":
        return "linux"
    else:
        return "unknown"


def get_platform_engines() -> List[tuple[str, Callable[[], Any]]]:
    """Return engine factories for the current platform."""
    platform_name = detect_platform()

    if platform_name == "windows":
        from tts_wrapper import SAPIClient, UWPClient

        return [
            ("SAPI5", SAPIClient),
            ("UWP", UWPClient),
        ]
    if platform_name == "macos":
        from tts_wrapper import eSpeakClient

        engines: List[tuple[str, Callable[[], Any]]] = [("eSpeak", eSpeakClient)]
        try:
            from tts_wrapper import AVSynthClient

            engines.insert(0, ("AVSynth", AVSynthClient))
        except ImportError:
            pass
        return engines
    if platform_name == "linux":
        from tts_wrapper import eSpeakClient

        return [("eSpeak", eSpeakClient)]

    return []


def _normalize_voices(
    voices: List[Dict[str, Any]], engine_name: str, platform_name: str
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for voice in voices:
        normalized.append(
            {
                "id": voice.get("id", ""),
                "name": voice.get("name", "Unknown"),
                "language_codes": voice.get("language_codes", []),
                "gender": voice.get("gender", "Unknown"),
                "engine": engine_name,
                "platform": platform_name,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return normalized


def _slugify_engine_name(name: str) -> str:
    return (
        name.lower()
        .replace(" ", "-")
        .replace("+", "plus")
        .replace("/", "-")
    )


def collect_platform_voices() -> List[Dict[str, Any]]:
    """
    Collect voices from the current platform using py3-tts-wrapper.

    Returns a list of voice dictionaries with standard schema.
    """
    platform_name = detect_platform()
    try:
        engines = get_platform_engines()
    except ImportError:
        print("Error: py3-tts-wrapper not installed.")
        print("Install with: pip install py3-tts-wrapper")
        return []

    if not engines:
        print(f"Unsupported platform: {platform_name}")
        return []

    all_voices: List[Dict[str, Any]] = []
    for engine_name, engine_ctor in engines:
        try:
            client = engine_ctor()
            voices = client.get_voices()
            normalized = _normalize_voices(voices, engine_name, platform_name)
            all_voices.extend(normalized)
            print(f"Collected {len(normalized)} voices from {engine_name}")
        except Exception as e:
            print(f"Skipping {engine_name}: {type(e).__name__}: {e}")

    print(f"Collected total {len(all_voices)} voices from {platform_name}")
    return all_voices


def _resolve_google_credentials_path() -> str | None:
    """Resolve Google credentials from file path or inline/base64 env vars."""
    file_path = Path(__file__).parent.parent / "data" / "raw" / "google-credentials.json"

    env_path = os.environ.get("GOOGLE_TTS_CREDENTIALS")
    if env_path and Path(env_path).exists():
        return env_path

    env_json = os.environ.get("GOOGLE_TTS_CREDENTIALS_JSON")
    if env_json:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(env_json, encoding="utf-8")
        return str(file_path)

    env_b64 = os.environ.get("GOOGLE_SA_FILE_B64")
    if env_b64:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b64decode(env_b64))
        return str(file_path)

    return None


def collect_online_voices() -> Dict[str, List[Dict[str, Any]]]:
    """Collect voices from credentialed online engines and local sherpaonnx."""
    from tts_wrapper import (
        ElevenLabsClient,
        GoogleClient,
        GoogleTransClient,
        MicrosoftClient,
        OpenAIClient,
        PlayHTClient,
        PollyClient,
        SherpaOnnxClient,
        UpliftAIClient,
        WatsonClient,
        WitAiClient,
    )

    platform_name = detect_platform()
    collected: Dict[str, List[Dict[str, Any]]] = {}

    google_credentials = _resolve_google_credentials_path()
    azure_key = os.environ.get("AZURE_TTS_KEY")
    azure_region = os.environ.get("AZURE_TTS_REGION")
    aws_region = os.environ.get("AWS_REGION")
    aws_id = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    watson_key = os.environ.get("WATSON_API_KEY")
    watson_region = os.environ.get("WATSON_REGION")
    watson_instance = os.environ.get("WATSON_INSTANCE_ID")
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    witai_token = os.environ.get("WITAI_TOKEN")
    openai_key = os.environ.get("OPENAI_API_KEY")
    playht_key = os.environ.get("PLAYHT_API_KEY")
    playht_user = os.environ.get("PLAYHT_USER_ID")
    upliftai_key = os.environ.get("UPLIFTAI_KEY")

    engine_factories: List[tuple[str, Callable[[], Any]]] = [
        ("Sherpa-ONNX", SherpaOnnxClient),
        ("GoogleTrans", GoogleTransClient),
    ]
    if google_credentials:
        engine_factories.append(
            ("Google Cloud", lambda: GoogleClient(credentials=google_credentials))
        )
    if azure_key and azure_region:
        engine_factories.append(
            ("Microsoft Azure", lambda: MicrosoftClient(credentials=(azure_key, azure_region)))
        )
    if aws_region and aws_id and aws_secret:
        engine_factories.append(
            ("AWS Polly", lambda: PollyClient(credentials=(aws_region, aws_id, aws_secret)))
        )
    if elevenlabs_key:
        engine_factories.append(("ElevenLabs", lambda: ElevenLabsClient(credentials=elevenlabs_key)))
    if watson_key and watson_region and watson_instance:
        engine_factories.append(
            ("IBM Watson", lambda: WatsonClient(credentials=(watson_key, watson_region, watson_instance)))
        )
    if witai_token:
        engine_factories.append(("Wit.ai", lambda: WitAiClient(credentials=witai_token)))
    if openai_key:
        engine_factories.append(("OpenAI", lambda: OpenAIClient(api_key=openai_key)))
    if playht_key and playht_user:
        engine_factories.append(
            ("PlayHT", lambda: PlayHTClient(credentials=(playht_key, playht_user)))
        )
    if upliftai_key:
        engine_factories.append(("UpliftAI", lambda: UpliftAIClient(api_key=upliftai_key)))

    for engine_name, factory in engine_factories:
        try:
            client = factory()
            voices = client.get_voices()
            normalized = _normalize_voices(voices, engine_name, platform_name)
            collected[engine_name] = normalized
            print(f"Collected {len(normalized)} voices from {engine_name}")
        except Exception as e:
            print(f"Skipping {engine_name}: {type(e).__name__}: {e}")

    return collected


def save_voices(voices: List[Dict[str, Any]], platform: str, output_dir: Path) -> int:
    """Save collected voices to JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{platform}-voices.json"

    existing_count = -1
    if output_file.exists():
        try:
            existing = json.loads(output_file.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                existing_count = len(existing)
        except Exception:
            existing_count = -1

    if existing_count >= 0 and len(voices) < existing_count:
        print(
            f"Keeping existing {output_file.name}: "
            f"{existing_count} voices > new {len(voices)}"
        )
        return existing_count

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(voices, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(voices)} voices to {output_file}")
    return len(voices)


def save_engine_voices(voices: List[Dict[str, Any]], engine_name: str, output_dir: Path) -> int:
    """Save voices for a specific engine to a dedicated JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify_engine_name(engine_name)
    output_file = output_dir / f"{slug}-voices.json"

    existing_count = -1
    if output_file.exists():
        try:
            existing = json.loads(output_file.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                existing_count = len(existing)
        except Exception:
            existing_count = -1

    if existing_count >= 0 and len(voices) < existing_count:
        print(
            f"Keeping existing {output_file.name}: "
            f"{existing_count} voices > new {len(voices)}"
        )
        return existing_count

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(voices, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(voices)} voices to {output_file}")
    return len(voices)


def main():
    """Main entry point for voice collection."""
    import argparse

    parser = argparse.ArgumentParser(description="Collect TTS voices from platform TTS engines")
    parser.add_argument(
        "--list", action="store_true", help="List available engines in py3-tts-wrapper"
    )
    parser.add_argument(
        "--list-all",
        action="store_true",
        help="List all client engines exposed by py3-tts-wrapper",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="Collect online/credentialed engines plus Sherpa-ONNX and save per-engine files",
    )

    args = parser.parse_args()

    if args.list_all:
        try:
            import tts_wrapper as t
        except ImportError:
            print("py3-tts-wrapper not installed")
            return

        print("All exposed client engines:")
        clients = []
        for name in dir(t):
            if name.endswith("Client"):
                obj = getattr(t, name)
                if inspect.isclass(obj):
                    clients.append((name, obj))

        for name, obj in sorted(clients):
            has_get_voices = hasattr(obj, "get_voices")
            try:
                signature = str(inspect.signature(obj))
            except Exception:
                signature = "(?)"
            print(f"  {name:18s} get_voices={has_get_voices:<5} sig={signature}")
        return

    if args.list:
        print("Available platform engines:")
        try:
            engines = get_platform_engines()
            if not engines:
                print(f"  No engine mapping for platform: {detect_platform()}")
                return

            for engine_name, engine_ctor in engines:
                try:
                    voices = engine_ctor().get_voices()
                    print(f"  {engine_name:7s}: Available ({len(voices)} voices)")
                except Exception as e:
                    print(f"  {engine_name:7s}: Unavailable ({type(e).__name__}: {e})")
        except ImportError:
            print("py3-tts-wrapper not installed")
        return

    if args.online:
        output_dir = Path(__file__).parent.parent / "data" / "raw"
        by_engine = collect_online_voices()
        total = 0
        for engine_name, engine_voices in by_engine.items():
            total += save_engine_voices(engine_voices, engine_name, output_dir)

        if total == 0:
            print("No online voices collected.")
            sys.exit(1)

        print(f"\nSuccessfully collected {total} online voices across {len(by_engine)} engines")
        return

    # Collect voices from current platform
    voices = collect_platform_voices()

    if not voices:
        print("No voices collected.")
        sys.exit(1)

    # Save to data/raw
    output_dir = Path(__file__).parent.parent / "data" / "raw"
    count = save_voices(voices, detect_platform(), output_dir)

    print(f"\nSuccessfully collected {count} voices from {detect_platform()}")
    print(f"Data saved to: {output_dir / f'{detect_platform()}-voices.json'}")


if __name__ == "__main__":
    main()
