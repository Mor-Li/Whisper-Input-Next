# Audio Archive Feature

## Feature Overview

Audio file preservation functionality for the Whisper-Input project:

### Audio File Archive 🎵

- **Description**: All recording files are automatically saved to `audio_archive/` directory
- **File naming**: Timestamp format `recording_YYYYMMDD_HHMMSS.wav`
- **File management**: Keep all files by default, no automatic deletion
- **Support range**: All three processors (LocalWhisper, Groq Whisper, SiliconFlow)

### Extended Timeout for Local Processing ⏰

- **Previous setting**: 30 second timeout limit
- **New setting**: 180 seconds (3 minutes) timeout limit
- **Scope**: Mainly for local whisper.cpp processor, API processors keep original shorter timeout

## Technical Implementation

### Audio Archive Feature

1. **Directory creation**: Automatically creates `audio_archive/` directory on startup
2. **File saving**: Original audio data saved to archive after each recording
3. **No file limits**: All recordings are preserved by default
4. **Error handling**: Archive failures don't affect normal transcription flow

### Timeout Settings

- **LocalWhisperProcessor**: `DEFAULT_TIMEOUT = 180` (3 minutes)
- **WhisperProcessor**: Maintains `DEFAULT_TIMEOUT = 20` (20 seconds)
- **SenseVoiceSmallProcessor**: Maintains `DEFAULT_TIMEOUT = 20` (20 seconds)

## Usage

### Normal Usage

No extra configuration needed, features work automatically:

1. Start program: `python main.py` or use `start.sh`
2. Perform recordings (any hotkey)
3. Recording files automatically saved to `audio_archive/` directory

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

# Backup archives to another location
cp -r audio_archive/ ~/backup_recordings/
```

## Configuration

### .gitignore Update

Automatically added `audio_archive/` to `.gitignore` file to prevent recording files from being accidentally committed to version control.

### Storage Considerations

- Each recording file size depends on duration (~32KB/second)
- No automatic file cleanup means storage grows over time
- Users can manually manage archives as needed

## Troubleshooting

### If archive directory not created

```bash
# Manually create directory
mkdir -p audio_archive
```

### If permission issues occur

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