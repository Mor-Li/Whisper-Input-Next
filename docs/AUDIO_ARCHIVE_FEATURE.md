# 音频存档功能说明

## 新增功能概述

本次更新为 Whisper-Input 项目添加了以下两个重要功能：

### 1. 音频文件保留功能 🎵

- **功能描述**：现在所有录音文件都会被自动保存到 `audio_archive/` 目录中，不再立即删除
- **文件命名**：使用时间戳格式 `recording_YYYYMMDD_HHMMSS.wav`
- **数量管理**：自动保留最新的 5 个录音文件，超过数量时自动删除旧文件
- **支持范围**：所有三种处理器（LocalWhisper、Groq Whisper、SiliconFlow）

### 2. 转录超时时间延长 ⏰

- **原设置**：30秒超时限制
- **新设置**：180秒（3分钟）超时限制
- **适用范围**：主要针对本地 whisper.cpp 处理器，API处理器保持原有较短超时时间

## 技术实现细节

### 音频存档功能

1. **目录创建**：程序启动时自动创建 `audio_archive/` 目录
2. **文件保存**：每次录音后，原始音频数据会被保存到存档目录
3. **数量控制**：使用文件修改时间排序，保留最新的5个文件
4. **错误处理**：如果保存失败，不会影响正常的转录流程

### 超时设置修改

- **LocalWhisperProcessor**：`DEFAULT_TIMEOUT = 180`（3分钟）
- **WhisperProcessor**：保持 `DEFAULT_TIMEOUT = 20`（20秒）
- **SenseVoiceSmallProcessor**：保持 `DEFAULT_TIMEOUT = 20`（20秒）

## 使用方法

### 正常使用

无需额外配置，功能会自动生效：

1. 启动程序：`python main.py` 或使用 `start.sh`
2. 进行录音操作（使用任何快捷键）
3. 录音文件会自动保存到 `audio_archive/` 目录

### 查看保存的录音

```bash
# 查看存档目录
ls -la audio_archive/

# 播放录音文件（macOS）
afplay audio_archive/recording_20250724_220003.wav
```

### 手动管理存档

```bash
# 清空所有存档（如果需要）
rm -rf audio_archive/

# 备份存档到其他位置
cp -r audio_archive/ ~/backup_recordings/
```

## 配置说明

### .gitignore 更新

已自动添加 `audio_archive/` 到 `.gitignore` 文件中，避免录音文件被意外提交到版本控制系统。

### 存储空间考虑

- 每个录音文件大小取决于录音时长（约 32KB/秒）
- 保留5个文件的存储空间通常在 1-5MB 之间
- 如需调整保留数量，可修改代码中的数字 `5`

## 故障排除

### 如果存档目录未创建

```bash
# 手动创建目录
mkdir -p audio_archive
```

### 如果出现权限问题

```bash
# 修复目录权限
chmod 755 audio_archive/
```

### 如果需要调整保留文件数量

在以下文件中修改数字 `5`：
- `src/transcription/local_whisper.py`
- `src/transcription/whisper.py`
- `src/transcription/senseVoiceSmall.py`

找到这行代码并修改数字：
```python
if len(wav_files) > 5:  # 修改这个数字
```

## 版本兼容性

- ✅ 兼容所有现有功能
- ✅ 不影响原有的转录流程
- ✅ 向后兼容，可安全升级

## 更新日志

- **2025-07-24**：
  - 新增音频文件自动保存功能
  - 将本地whisper.cpp超时时间从30秒延长到180秒
  - 为所有处理器添加统一的存档管理功能
  - 更新.gitignore以忽略音频存档目录 