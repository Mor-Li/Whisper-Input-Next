# Audio Archive Feature

## Feature Overview

Audio file preservation functionality for the Whisper-Input project:

### Audio File Archive 🎵

- **Description**: All recording files are automatically saved to `audio_archive/` directory
- **File naming**: Timestamp format `recording_YYYYMMDD_HHMMSS.wav`
- **Storage policy**: **Keep all files by default** (no automatic deletion)
- **Support**: All three processors (LocalWhisper, Groq Whisper, SiliconFlow)

### Extended Transcription Timeout ⏰

- **Previous**: 30-second timeout limit
- **Current**: 180-second (3-minute) timeout limit
- **Scope**: Primarily for local whisper.cpp processor

## Technical Implementation

### Audio Archive

1. **Directory creation**: Auto-create `audio_archive/` directory on startup
2. **File saving**: Original audio data saved to archive after each recording
3. **Storage policy**: Keep all files, no automatic cleanup
4. **Error handling**: Save failures don't affect normal transcription flow

### Timeout Settings

- **LocalWhisperProcessor**: `DEFAULT_TIMEOUT = 180` (3 minutes)
- **WhisperProcessor**: `DEFAULT_TIMEOUT = 20` (20 seconds)
- **SenseVoiceSmallProcessor**: `DEFAULT_TIMEOUT = 20` (20 seconds)

## Usage

### Normal Operation

No additional configuration needed:

1. Start program: `python main.py` or use `start.sh`
2. Perform recordings (any hotkey)
3. Audio files automatically saved to `audio_archive/`

### View Saved Recordings

```bash
# View archive directory
ls -la audio_archive/

# Play recording (macOS)
afplay audio_archive/recording_20250724_220003.wav
```

### Manual Archive Management

```bash
# Clear all archives (if needed)
rm -rf audio_archive/

# Backup archives
cp -r audio_archive/ ~/backup_recordings/

# Clean old files manually (optional)
# Remove files older than 30 days
find audio_archive/ -name "*.wav" -mtime +30 -delete
```

## Configuration

### .gitignore Update

`audio_archive/` automatically added to `.gitignore` to prevent accidental commits.

### Storage Considerations

- Each recording file size depends on duration (~32KB/second)
- No automatic limit - files accumulate over time
- Manual cleanup recommended if storage becomes an issue

## Troubleshooting

### Archive Directory Not Created

```bash
# Manually create directory
mkdir -p audio_archive
```

### Permission Issues

```bash
# Fix directory permissions
chmod 755 audio_archive/
```

## Version Compatibility

- ✅ Compatible with all existing features
- ✅ No impact on original transcription flow
- ✅ Backward compatible, safe to upgrade

## Changelog

- **2025-07-25**:
  - **BREAKING**: Changed from 5-file limit to keeping all files by default
  - Removed automatic file cleanup for better data preservation
  - Users can manually manage archives if needed 