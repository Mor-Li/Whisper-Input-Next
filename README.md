# Whisper-Input-Next - Enhanced Voice Transcription Tool

<p align="center">
  <img src="docs/whisper_claudecode.png" alt="Project Poster" />
</p>

<p align="center">
  <a href="./VERSION">
    <img src="https://img.shields.io/badge/version-3.1.0-blue.svg" alt="Version" />
  </a>
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/python-3.12+-green.svg" alt="Python" />
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  </a>
  <a href="docs/README_zh-CN.md">
    <img src="https://img.shields.io/badge/docs-中文文档-red.svg" alt="Chinese Documentation" />
  </a>
</p>

An intelligent voice transcription input tool supporting multiple transcription services and high-quality speech recognition features.

## 🚀 Project Background

This project is based on [ErlichLiu/Whisper-Input](https://github.com/ErlichLiu/Whisper-Input) for secondary development. The original project has been inactive for months, so we have made extensive feature expansions and architectural optimizations, adding important features like OpenAI GPT-4o transcribe integration, audio archiving, local whisper support, and more. [Why use this project?](./docs/[V3.0.0]_知乎blog.md)

## ✨ Key Features

### 🎯 Core Functions
- **Multi-platform Transcription Services**: Support for OpenAI GPT-4o transcribe, GROQ, SiliconFlow, local whisper.cpp
- **Smart Hotkeys**: Ctrl+F (OpenAI high-quality) / Ctrl+I (local cost-saving mode)
- **Audio Archive**: Automatically save all recordings, support history playback
- **Failure Retry**: Intelligent error handling and retry mechanism

### 🔧 Technical Features
- **Dual Processor Architecture**: OpenAI + Local processors working simultaneously
- **180s Long Audio Support**: Support up to 3 minutes of continuous recording
- **Smart Status Indicators**: Simple numeric status display (0, 1, !)
- **Cache System**: Audio archive with transcription result caching

### 🌟 User Experience
- **No Clipboard Pollution**: Clean status display without interfering with system clipboard
- **One-click Retry**: Failed transcriptions can be retried without re-recording
- **Real-time Input**: Transcription results appear directly at cursor position
- **Privacy Protection**: Local processing option, data not uploaded

## 📦 Quick Start

### Environment Requirements
- Python 3.12+
- macOS/Linux (Windows support in development)
- Network connection (only required for cloud services)
- **Local whisper.cpp** (required when using local transcription features)

### Installation Steps

1. **Clone Project**
```bash
git clone https://github.com/Mor-Li/Whisper-Input-Next.git
cd Whisper-Input-Next
```

2. **Create Virtual Environment**
```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# or venv\\Scripts\\activate  # Windows
```

3. **Install Dependencies**
```bash
pip install -r requirements.txt
```

4. **Install Local whisper.cpp (Optional, required for local transcription)**
```bash
# Clone whisper.cpp repository
git clone https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp

# Compile (macOS/Linux)
make

# Download model file (recommend large-v3)
bash ./models/download-ggml-model.sh large-v3

# Record whisper-cli path for later configuration in .env file
echo "Whisper CLI Path: $(pwd)/build/bin/whisper-cli"
cd ..
```

5. **Configure Environment Variables**
```bash
cp env.example .env
# Edit .env file, configure necessary parameters:
# - OFFICIAL_OPENAI_API_KEY: OpenAI API key (required)
# - WHISPER_CLI_PATH: whisper.cpp executable path (required for local transcription)
# - WHISPER_MODEL_PATH: whisper model file path (required for local transcription)
```

6. **Run Program**
```bash
python main.py
# or use startup script
chmod +x start.sh
./start.sh
```

### ⚠️ Important Notes

**Required Configuration:**
- `OFFICIAL_OPENAI_API_KEY`: OpenAI GPT-4o transcribe API key
- `WHISPER_CLI_PATH`: Local whisper.cpp executable absolute path
- `WHISPER_MODEL_PATH`: whisper model file path (relative to whisper.cpp root directory)

**whisper.cpp Installation Guide:**
1. Clone and compile from [whisper.cpp repository](https://github.com/ggerganov/whisper.cpp)
2. Download large-v3 model: `bash ./models/download-ggml-model.sh large-v3`
3. Configure correct paths in .env

## ⚙️ Configuration Guide

### Environment Variable Configuration

Configure the following parameters in the `.env` file:

```bash
# Service platform selection (recommend using our maintained dual-platform configuration)
SERVICE_PLATFORM=openai&local  # Our primarily maintained configuration

# OpenAI configuration (required)
OFFICIAL_OPENAI_API_KEY=sk-proj-xxx

# Local whisper.cpp configuration (required for local transcription)
WHISPER_CLI_PATH=/path/to/whisper.cpp/build/bin/whisper-cli
WHISPER_MODEL_PATH=models/ggml-large-v3.bin

# Keyboard shortcut configuration
TRANSCRIPTIONS_BUTTON=f
TRANSLATIONS_BUTTON=ctrl
SYSTEM_PLATFORM=mac  # mac/win

# Feature switches
CONVERT_TO_SIMPLIFIED=false
ADD_SYMBOL=false
OPTIMIZE_RESULT=false
```

**Important Note**: 
- This project primarily maintains `SERVICE_PLATFORM=openai&local` configuration
- This is our recommended and most thoroughly tested configuration
- Other single-platform configurations (groq, siliconflow, etc.) are maintained for compatibility only

### Quick Start with Aliases (Recommended)

Add these aliases to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
alias whisper_input='cd /path/to/Whisper-Input-Next && ./start.sh'
alias whisper_input_off='tmux kill-session -t whisper-input'
```

Replace `/path/to/Whisper-Input-Next` with your actual project path.

### Hotkey Instructions

| Hotkey | Function | Service | Features |
|--------|----------|---------|-----------|
| `Ctrl+F` | High-quality transcription | OpenAI GPT-4o transcribe | Built-in punctuation, highest quality |
| `Ctrl+I` | Local transcription | whisper.cpp | Offline processing, privacy protection |

### Status Indicators

The program displays concise status indicators at the cursor position during runtime:

| Status | Meaning | Action |
|--------|---------|--------|
| `0` | Recording | Press hotkey again to stop recording |
| `1` | Transcribing | Please wait for transcription to complete |
| `!` | Transcription failed/error | Press `Ctrl+F` again to retry (audio saved) |

**Design Optimizations**:
- Use concise numeric status, avoid complex emoji symbols
- No system clipboard pollution, display only at cursor position
- Clear and intuitive status, easy to quickly identify

**Retry Mechanism Instructions**:
- When transcription fails, the system saves the recording and displays `!` status
- No need to re-record, simply press `Ctrl+F` to retry
- Retry uses previously saved audio until transcription succeeds

## 📚 Feature Documentation

- [🔊 Audio Archive Feature](./docs/[V3.0.0]_AUDIO_ARCHIVE_FEATURE.md) - *Introduced in v3.0.0*
- [🤖 Kimi Polish Integration](./docs/[DEPRECATED]_KIMI_USAGE.md) - *Deprecated*
- [📊 Status Display Improvements](./docs/[V3.0.0]_STATUS_DISPLAY_IMPROVEMENTS.md) - *Introduced in v3.0.0*
- [🔄 Branch Differences Comparison](./docs/[V3.0.0]_BRANCH_DIFFERENCES.md) - *Introduced in v3.0.0*
- [📋 Version Control Documentation](./docs/[V3.0.0]_VERSION_CONTROL.md) - *Established in v3.0.0*

## 🛠️ Development Status

### ✅ Completed Features
- [x] OpenAI GPT-4o transcribe integration
- [x] Audio archive system
- [x] Local whisper support
- [x] Dual processor architecture
- [x] Smart retry mechanism
- [x] Project documentation improvement
- [x] 10-minute recording limit protection
- [x] Status indicator delay optimization
- [x] Audio format conversion support (m4a to wav)
- [x] Bilingual documentation system
- [x] GPT-4o terminology standardization

### 🚧 In Development  
*No features currently in development*

### 📋 Planned Features
*No features currently planned*

### 🧪 Experimental Features History

#### iOS Keyboard Extension Experiment (August 14, 2025)
**Status**: ❌ Discontinued due to Apple's restrictions  
Attempted to create iOS keyboard extension but discovered that even Sogou Input Method cannot directly record audio in keyboard extensions due to Apple's system limitations. iOS voice input is currently not feasible as a seamless keyboard extension.

## 🤝 Contributing Guidelines

We welcome all forms of contributions! Whether it's:

- 🐛 **Bug Reports**: Found an issue? [Create an Issue](https://github.com/Mor-Li/Whisper-Input-Next/issues)
- 💡 **Feature Suggestions**: Have great ideas? [Start a Discussion](https://github.com/Mor-Li/Whisper-Input-Next/discussions)
- 📝 **Code Contributions**: Submit Pull Requests
- 📚 **Documentation Improvements**: Help improve documentation
- 🌍 **Translations**: Help translate to more languages

### Development Environment Setup

```bash
# Clone repository
git clone https://github.com/Mor-Li/Whisper-Input-Next.git
cd Whisper-Input-Next

# Create development environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start development
python main.py
```

## 🙏 Acknowledgments

- Thanks to [ErlichLiu/Whisper-Input](https://github.com/ErlichLiu/Whisper-Input) for the original project foundation
- Thanks to OpenAI for providing excellent transcription API services
- Thanks to [whisper.cpp](https://github.com/ggerganov/whisper.cpp) community for local processing support
- Thanks to all contributors and users for their support

## 📞 Contact Information

- **Project Address**: https://github.com/Mor-Li/Whisper-Input-Next  
- **Issue Reports**: [Issues](https://github.com/Mor-Li/Whisper-Input-Next/issues)
- **Feature Suggestions**: [Discussions](https://github.com/Mor-Li/Whisper-Input-Next/discussions)

---

**⭐ If this project helps you, please give it a Star for support!**