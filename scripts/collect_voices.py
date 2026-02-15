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
import platform
import sys
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


def save_voices(voices: List[Dict[str, Any]], platform: str, output_dir: Path) -> int:
    """Save collected voices to JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{platform}-voices.json"

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
