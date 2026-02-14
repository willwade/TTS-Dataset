#!/usr/bin/env python3
"""
Simple TTS voice collection using py3-tts-wrapper.

Collects voices from:
- Windows: SAPI5
- macOS: Native Speech (AVSynth or NSSS)
- Linux: eSpeak

Output: data/raw/{platform}-voices.json
"""

import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from tts_wrapper import SAPIClient, SAPITTS
except ImportError:
    print("Error: py3-tts-wrapper not installed.")
    print("Install with: pip install py3-tts-wrapper[sapi]")
    sys.exit(1)


def detect_platform() -> str:
    """Detect the current platform for voice collection."""
    system = platform.system().lower()
    if system == 'windows':
        return 'windows'
    elif system == 'darwin':
        return 'macos'
    elif system == 'linux':
        return 'linux'
    else:
        return 'unknown'


def collect_platform_voices() -> List[Dict[str, Any]]:
    """
    Collect voices from the current platform using py3-tts-wrapper.

    Returns a list of voice dictionaries with standard schema.
    """
    platform = detect_platform()

    if platform == 'windows':
        engine_name = 'SAPI5'
    elif platform == 'macos':
        engine_name = 'NSSS'  # or 'AVSynth'
    elif platform == 'linux':
        engine_name = 'eSpeak'
    else:
        print(f"Unsupported platform: {platform}")
        return []

    if not SAPIClient:
        print(f"{engine_name} client not available. Install: pip install py3-tts-wrapper[sapi]")
        return []

    try:
        client = SAPIClient(engine_name)
        tts = SAPITTS(client)
        voices = tts.get_voices()

        # Normalize to standard schema
        normalized = []
        for voice in voices:
            normalized.append({
                'id': voice.get('id', ''),
                'name': voice.get('name', 'Unknown'),
                'language_codes': voice.get('language_codes', []),
                'gender': voice.get('gender', 'Unknown'),
                'engine': engine_name,
                'platform': platform,
                'collected_at': datetime.now(timezone.utc).isoformat()
            })

        print(f"Collected {len(normalized)} voices from {platform}")
        return normalized

    except Exception as e:
        print(f"Error collecting {engine_name} voices: {e}")
        return []


def save_voices(voices: List[Dict[str, Any]], platform: str, output_dir: Path) -> int:
    """Save collected voices to JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{platform}-voices.json"

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(voices, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(voices)} voices to {output_file}")
    return len(voices)


def main():
    """Main entry point for voice collection."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Collect TTS voices from platform TTS engines'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List available engines in py3-tts-wrapper'
    )

    args = parser.parse_args()

    if args.list:
        # List what's available in py3-tts-wrapper
        try:
            from tts_wrapper import SAPIClient
            print("Available engines in py3-tts-wrapper:")
            for engine in ['sapi', 'nsss', 'espeak']:
                try:
                    client = SAPIClient(engine)
                    print(f"  {engine:5s}: Available")
                    tts = SAPITTS(client)
                    voices = tts.get_voices()
                    print(f"    Voices: {len(voices)}")
                except Exception:
                    pass
        except ImportError:
            print("py3-tts-wrapper not installed")
        return

    # Collect voices from current platform
    voices = collect_platform_voices()

    if not voices:
        print("No voices collected.")
        sys.exit(1)

    # Save to data/raw
    output_dir = Path(__file__).parent.parent / 'data' / 'raw'
    count = save_voices(voices, detect_platform(), output_dir)

    print(f"\nSuccessfully collected {count} voices from {detect_platform()}")
    print(f"Data saved to: {output_dir / f'{detect_platform()}-voices.json'}")


if __name__ == '__main__':
    main()
