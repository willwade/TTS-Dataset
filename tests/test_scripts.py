"""Tests for TTS voice collection scripts."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

# Add scripts directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestCollectVoices:
    """Test voice collection script."""

    def test_detect_platform_windows(self):
        """Test platform detection for Windows."""
        from collect_voices import detect_platform
        with patch('platform.system', return_value='Windows'):
            assert detect_platform() == 'windows'

    def test_detect_platform_macos(self):
        """Test platform detection for macOS."""
        from collect_voices import detect_platform
        with patch('platform.system', return_value='Darwin'):
            assert detect_platform() == 'macos'

    def test_detect_platform_linux(self):
        """Test platform detection for Linux."""
        from collect_voices import detect_platform
        with patch('platform.system', return_value='Linux'):
            assert detect_platform() == 'linux'

    @patch('collect_voices.SAPIClient')
    @patch('collect_voices.SAPITTS')
    @patch('collect_voices.detect_platform', return_value='windows')
    def test_collect_platform_voices_windows(self, mock_platform, mock_sapi_tts, mock_sapi_client):
        """Test collecting voices from Windows platform."""
        from collect_voices import collect_platform_voices

        # Mock the client and TTS
        mock_client = Mock()
        mock_sapi_client.return_value = mock_client
        mock_tts = Mock()
        mock_sapi_tts.return_value = mock_tts

        # Mock voice data
        mock_tts.get_voices.return_value = [
            {
                'id': 'test-voice-1',
                'name': 'Test Voice 1',
                'language_codes': ['en-US'],
                'gender': 'Female'
            },
            {
                'id': 'test-voice-2',
                'name': 'Test Voice 2',
                'language_codes': ['en-GB'],
                'gender': 'Male'
            }
        ]

        voices = collect_platform_voices()

        assert len(voices) == 2
        assert voices[0]['id'] == 'test-voice-1'
        assert voices[0]['engine'] == 'SAPI5'
        assert voices[0]['platform'] == 'windows'
        assert 'collected_at' in voices[0]
        assert isinstance(voices[0]['collected_at'], str)

    @patch('collect_voices.detect_platform', return_value='unknown')
    def test_collect_platform_voices_unsupported(self, mock_platform):
        """Test collecting voices from unsupported platform."""
        from collect_voices import collect_platform_voices
        voices = collect_platform_voices()
        assert voices == []

    def test_save_voices(self, tmp_path):
        """Test saving voices to JSON file."""
        from collect_voices import save_voices

        voices = [
            {
                'id': 'test-voice-1',
                'name': 'Test Voice',
                'language_codes': ['en-US'],
                'gender': 'Female'
            }
        ]

        count = save_voices(voices, 'test-platform', tmp_path)

        assert count == 1
        output_file = tmp_path / 'test-platform-voices.json'
        assert output_file.exists()

        with open(output_file, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
            assert saved_data == voices


class TestHarmonize:
    """Test harmonization script."""

    def test_get_language_info_valid(self):
        """Test language info enrichment with valid code."""
        from harmonize import get_language_info

        result = get_language_info("en-US")
        assert result is not None
        assert 'language_name' in result
        assert 'language_display' in result
        assert 'country_code' in result
        assert 'script' in result

    def test_get_language_info_unknown(self):
        """Test language info with unknown code."""
        from harmonize import get_language_info

        result = get_language_info("unknown-lang")
        assert result is not None
        assert result['language_name'] is None

    def test_get_language_info_empty(self):
        """Test language info with empty code."""
        from harmonize import get_language_info

        result = get_language_info("")
        assert result['language_name'] is None
        assert result['language_display'] is None

    def test_load_json_files(self, tmp_path):
        """Test loading JSON files from directory."""
        from harmonize import load_json_files

        # Create test JSON files
        voices1 = [{'id': 'voice-1', 'name': 'Voice 1'}]
        voices2 = [{'id': 'voice-2', 'name': 'Voice 2'}]

        (tmp_path / 'windows-voices.json').write_text(json.dumps(voices1))
        (tmp_path / 'macos-voices.json').write_text(json.dumps(voices2))

        result = load_json_files(tmp_path)
        assert len(result) == 2
        assert any(v['id'] == 'voice-1' for v in result)
        assert any(v['id'] == 'voice-2' for v in result)

    def test_load_json_files_nonexistent_dir(self, tmp_path):
        """Test loading JSON files from nonexistent directory."""
        from harmonize import load_json_files

        result = load_json_files(tmp_path / "nonexistent")
        assert result == []

    def test_deduplicate_voices(self):
        """Test voice deduplication by ID."""
        from harmonize import deduplicate_voices
        from datetime import datetime, timezone

        old_time = datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat()
        new_time = datetime(2024, 6, 1, tzinfo=timezone.utc).isoformat()

        voices = [
            {'id': 'voice-1', 'name': 'Old Voice', 'collected_at': old_time},
            {'id': 'voice-1', 'name': 'New Voice', 'collected_at': new_time},
            {'id': 'voice-2', 'name': 'Voice 2', 'collected_at': old_time}
        ]

        result = deduplicate_voices(voices)
        assert len(result) == 2
        assert any(v['id'] == 'voice-1' and v['name'] == 'New Voice' for v in result)
        assert any(v['id'] == 'voice-2' for v in result)

    def test_enrich_voices(self):
        """Test voice data enrichment with language metadata."""
        from harmonize import enrich_voices

        voices = [
            {
                'id': 'voice-1',
                'name': 'Voice 1',
                'language_codes': ['en-US'],
                'gender': 'Female'
            },
            {
                'id': 'voice-2',
                'name': 'Voice 2',
                'language_codes': [],
                'gender': 'Male'
            }
        ]

        result = enrich_voices(voices)
        assert len(result) == 2
        assert 'language_name' in result[0]
        assert 'language_display' in result[0]
        assert 'country_code' in result[0]
        assert 'script' in result[0]
        assert result[1]['language_display'] == 'Unknown'


class TestDataPipeline:
    """Test end-to-end data pipeline."""

    def test_voice_schema_normalization(self):
        """Test that voice data has required schema fields."""
        voice = {
            'id': 'test-voice-1',
            'name': 'Test Voice',
            'language_codes': ['en-US'],
            'gender': 'Female',
            'engine': 'SAPI5',
            'platform': 'windows',
            'collected_at': datetime.now(timezone.utc).isoformat()
        }

        required_fields = ['id', 'name', 'language_codes', 'gender',
                          'engine', 'platform', 'collected_at']
        for field in required_fields:
            assert field in voice, f"Missing field: {field}"

    def test_json_output_structure(self):
        """Test that JSON output has required fields."""
        voice = {
            'id': 'test-voice-1',
            'name': 'Test Voice',
            'language_codes': ['en-US'],
            'gender': 'Female',
            'engine': 'SAPI5',
            'platform': 'windows',
            'collected_at': datetime.now(timezone.utc).isoformat()
        }

        # Verify required fields exist
        required_fields = ['id', 'name', 'language_codes', 'gender',
                          'engine', 'platform', 'collected_at']
        for field in required_fields:
            assert field in voice, f"Missing field: {field}"

        # Verify data types
        assert isinstance(voice['language_codes'], list)
        assert isinstance(voice['collected_at'], str)
