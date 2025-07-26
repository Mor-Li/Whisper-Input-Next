# Whisper-Input - Enhanced Voice Transcription Tool

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](./VERSION)
[![Python](https://img.shields.io/badge/python-3.8+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

一个基于语音转录的智能输入工具，支持多种转录服务和高质量的语音识别功能。

## 🚀 项目背景

本项目基于 [ErlichLiu/Whisper-Input](https://github.com/ErlichLiu/Whisper-Input) 进行二次开发。原项目已停止维护数月，我们在其基础上进行了大量功能扩展和架构优化，添加了OpenAI GPT-4o transcribe集成、音频存档、本地whisper支持等重要功能。

## ✨ 主要特性

### 🎯 核心功能
- **多平台转录服务**: 支持OpenAI GPT-4o transcribe、GROQ、SiliconFlow、本地whisper.cpp
- **智能快捷键**: Ctrl+F (OpenAI高质量) / Ctrl+I (本地省钱模式)
- **音频存档**: 自动保存所有录音，支持历史回放
- **失败重试**: 智能错误处理和重试机制
- **实时状态**: 直观的录音和处理状态显示

### 🔧 技术特性
- **双处理器架构**: 同时支持云端和本地转录
- **180秒超时**: OpenAI专用长时间超时支持
- **自动标点**: GPT-4o transcribe自带标点符号
- **隐私保护**: 本地处理选项，数据不上传

## 📦 快速开始

### 环境要求
- Python 3.8+
- macOS/Linux (Windows支持开发中)
- 网络连接 (仅云端服务需要)

### 安装步骤

1. **克隆项目**
```bash
git clone https://github.com/Mor-Li/Whisper-Input.git
cd Whisper-Input
```

2. **创建虚拟环境**
```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# 或 venv\\Scripts\\activate  # Windows
```

3. **安装依赖**
```bash
pip install -r requirements.txt
```

4. **配置环境变量**
```bash
cp .env.example .env
# 编辑 .env 文件，添加你的API密钥
```

5. **运行程序**
```bash
python main.py
# 或使用启动脚本
chmod +x start.sh
./start.sh
```

## ⚙️ 配置说明

### 环境变量配置

在 `.env` 文件中配置以下参数：

```bash
# 服务平台选择 (推荐使用我们维护的双平台配置)
SERVICE_PLATFORM=openai&local  # 我们主要维护的配置

# OpenAI 配置 (必需)
OFFICIAL_OPENAI_API_KEY=sk-proj-xxx

# 键盘快捷键配置
TRANSCRIPTIONS_BUTTON=f
TRANSLATIONS_BUTTON=ctrl
SYSTEM_PLATFORM=mac  # mac/win

# 功能开关
CONVERT_TO_SIMPLIFIED=false
ADD_SYMBOL=false
OPTIMIZE_RESULT=false
```

**重要说明**: 
- 本项目主要维护 `SERVICE_PLATFORM=openai&local` 配置
- 这是我们推荐和测试最充分的配置
- 其他单平台配置（groq、siliconflow等）仅作兼容性保留

### 快捷键说明

| 快捷键 | 功能 | 服务 | 特点 |
|--------|------|------|------|
| `Ctrl+F` | 高质量转录 | OpenAI GPT-4o transcribe | 自带标点，质量最高 |
| `Ctrl+I` | 本地转录 | whisper.cpp | 离线处理，隐私保护 |

## 📚 功能文档

- [🔊 音频存档功能](./docs/AUDIO_ARCHIVE_FEATURE.md)
- [🤖 Kimi润色集成](./docs/KIMI_USAGE.md) 
- [📊 状态显示优化](./docs/STATUS_DISPLAY_IMPROVEMENTS.md)
- [🔄 分支差异对比](./docs/BRANCH_DIFFERENCES.md)

## 🛠️ 开发状态

### ✅ 已完成功能
- [x] OpenAI GPT-4o transcribe集成 (180秒超时)
- [x] 双处理器架构 (云端+本地)
- [x] 音频存档系统 + 转录缓存(cache.json)
- [x] 智能重试机制 (多次失败循环重试)
- [x] 状态显示优化 (0→1→!)
- [x] 本地whisper.cpp支持
- [x] 项目文档完善

### 🚧 正在开发  
- [ ] 配置界面开发
- [ ] Windows平台适配
- [ ] 单元测试完善
- [ ] 性能监控系统

### 📋 计划功能
- [ ] 更多云端服务支持
- [ ] 语音命令控制
- [ ] 批量音频处理
- [ ] Web界面

## 🤝 贡献指南

欢迎提交Issues和Pull Requests！

### 开发环境设置
```bash
# 克隆项目
git clone https://github.com/Mor-Li/Whisper-Input.git
cd Whisper-Input

# 设置开发模式
pip install -r requirements.txt
pip install -e .

# 运行测试
python -m pytest tests/
```

### 提交规范
- feat: 新功能
- fix: 修复问题  
- docs: 文档更新
- style: 代码风格
- refactor: 重构
- test: 测试相关

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

## 🙏 致谢

- 感谢 [ErlichLiu](https://github.com/ErlichLiu) 提供的原始项目基础
- 感谢 OpenAI 提供的强大转录服务
- 感谢所有贡献者和用户的支持

## 📞 联系方式

- **项目地址**: https://github.com/Mor-Li/Whisper-Input  
- **问题报告**: [Issues](https://github.com/Mor-Li/Whisper-Input/issues)
- **功能建议**: [Discussions](https://github.com/Mor-Li/Whisper-Input/discussions)

---

**⭐ 如果这个项目对你有帮助，请给个Star支持一下！**