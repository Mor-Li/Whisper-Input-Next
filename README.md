# Whisper Input

Whisper Input 是受到即友[FeiTTT](https://web.okjike.com/u/DB98BE7A-9DBB-4730-B6B9-2DC883B986B1)启发做的一个简单的 python 代码。可以实现按下 Option 按钮开始录制，抬起按钮就结束录制，并调用 Groq `Whisper Large V3 Turbo` 模型进行转译，由于 Groq 的速度非常快，所以大部分的语音输入都可以在 1-2s 内反馈。并且得益于 whisper 的强大能力，转译效果非常不错。

- 🎉🎉由于目前已经发现了更好用的语音输入软件[WhisperKeyBoard](https://whisperkeyboard.app/)，非常推荐大家可以直接使用这款软件即可。Whisper Input 的中心将继续回到 Voice + Agents 上。

- 支持由 SiliconFlow 托管的 `FunAudioLLM/SenseVoiceSmall` 模型，速度比 Groq 托管的 `Whisper Large V3 Turbo` 更快，识别更准确，并且自带标点符号。**最重要的是普通用户也无用量限制！**

## 当前阶段工作（20250129 更新）
当前阶段正在构建一个简易的 macOS 客户端。考虑到使用这个项目的大部分用户都是非程序员背景的，并且通常大量依赖语音输入功能的用户也有一部分是视力障碍用户，所以近期在着重做 macOS 客户端以及无障碍开发，未来将上线网站对外公布 macOS 客户端。如果你对 Windows 客户端的开发以及无障碍开发有经验和兴趣，欢迎与我联系：微信 geekthings。

## 功能

| 功能           | 快捷键                          |
| -------------- | ------------------------------- |
| 多语言语音转译 | Option 或者 Alt                 |
| 中文翻译为英文 | Shift + Option 或者 Shift + Alt |



查看[视频效果演示](https://img.erlich.fun/personal-blog/uPic/WhisperInputV02_compressed.mp4)



**重点：Groq 和 SiliconFlow 都提供免费用量，并且都足够，无需付费，无需绑定信用卡**


## 使用方法

> 目前支持三种 ASR 模型，分别是本地 `whisper.cpp` 模型、Groq 托管的 `Whisper Large V3 系列` 以及 SiliconFlow 托管的 `FunAudioLLM/SenseVoiceSmall` 系列。以下配置三选一即可。

### 前提
请确保你的本地有 Python 环境，并且 Python 版本不低于 3.10。
#### 3.13.1会有光标切换窗口报错的问题，这是个known issue，暂无解决方案，3.12.5无报错

### 本地 whisper.cpp 模型配置方法 【推荐：完全本地化，无需网络，速度快】
1. 安装并编译 whisper.cpp：
    ```bash
    git clone https://github.com/ggerganov/whisper.cpp.git
    cd whisper.cpp
    make
    ```

2. 下载模型文件（large-v3模型约1.5GB）：
    ```bash
    # 下载large-v3模型
    bash ./models/download-ggml-model.sh large-v3
    ```

3. 克隆并配置本项目：
    ```bash
    git clone git@github.com:ErlichLiu/Whisper-Input.git
    cd Whisper-Input
    ```

4. 创建虚拟环境 【推荐】
    ```bash
    python -m venv venv
    ```

5. 重命名 `.env` 文件
    ```bash
    cp .env.example .env
    ```

6. 配置 `.env` 文件，设置本地whisper.cpp路径：
    ```bash
    SERVICE_PLATFORM=local
    WHISPER_CLI_PATH=/path/to/your/whisper.cpp/build/bin/whisper-cli
    WHISPER_MODEL_PATH=models/ggml-large-v3.bin
    ```

7. 激活虚拟环境
    ```bash
    # macOS / Linux
    source venv/bin/activate
    
    # Windows
    .\venv\Scripts\activate
    ```

8. 安装依赖
    ```bash
    pip install pip-tools
    pip-compile requirements.in
    pip install -r requirements.txt
    ```

9. 测试本地whisper.cpp配置（可选）
    ```bash
    python test_local_whisper.py
    ```

10. 运行程序
    ```bash
    python main.py
    ```

### FunAudioLLM/SenseVoiceSmall 模型配置方法
1. 注册 SiliconFlow 账户：https://cloud.siliconflow.cn/i/RXikvHE2
2. 创建并复制免费的 API KEY：https://cloud.siliconflow.cn/account/ak
3. 打开 `终端` ，进入到想要下载项目的文件夹
    ```bash
    git clone git@github.com:ErlichLiu/Whisper-Input.git
    ```
4. 创建虚拟环境 【推荐】
    ```bash
    python -m venv venv
    ```

5. 重命名 `.env` 文件
    ```bash
    cp .env.example .env
    ```

6. 粘贴在第 2 步复制的 API KEY 到 `.env`  文件，效果类似
    ```bash
    SERVICE_PLATFORM=siliconflow
    SILICONFLOW_API_KEY=sk_z8q3rXrQM3o******************8dQEJCYz3QTJQYZ
    ```

7. 在最好不需要关闭的 `终端` 内进入到对应文件夹，然后激活虚拟环境
    ```bash
    # macOS / Linux
    source venv/bin/activate
    
    # Windows
    .\venv\Scripts\activate
    ```

8. 安装依赖
    ```bash
    pip install pip-tools
    pip-compile requirements.in
    pip install -r requirements.txt
    ```

9. 运行程序
    ```bash
    python main.py
    ```


### Groq Whisper Large V3 模型配置方法
1. 注册 Groq 账户：https://console.groq.com/login
2. 复制 Groq 免费的 API KEY：https://console.groq.com/keys
3. 打开 `终端` ，进入到想要下载项目的文件夹
    ```bash
    git clone git@github.com:ErlichLiu/Whisper-Input.git
    ```
4. 创建虚拟环境 【推荐】
    ```bash
    python -m venv venv
    ```

5. 重命名 `.env` 文件
    ```bash
    cp .env.example .env
    ```

6. 粘贴在第 2 步复制的 API KEY 到 `.env`  文件，效果类似
    ```bash
    SERVICE_PLATFORM=groq
    GROQ_API_KEY=gsk_z8q3rXrQM3o******************8dQEJCYz3QTJQYZ
    ```

7. 在最好不需要关闭的 `终端` 内进入到对应文件夹，然后激活虚拟环境
    ```bash
    # macOS / Linux
    source venv/bin/activate
    
    # Windows
    .\venv\Scripts\activate
    ```

8. 安装依赖
    ```bash
    pip install pip-tools
    pip-compile requirements.in
    pip install -r requirements.txt
    ```

9. 运行程序
    ```bash
    python main.py
    ```

    

**🎉  此时你就可以按下 Option 按钮开始语音识别录入啦！**



![image-20250111140954085](https://img.erlich.fun/personal-blog/uPic/image-20250111140954085.png)

## Tips

由于这个程序需要一直在后台运行，所以最好找一个自己不会经常下意识关掉的终端或者终端里的 Tab 来运行，不然很容易会不小心关掉。



关注作者个人网站，了解更多项目: https://erlich.fun





## 未来计划

[✅] 多语言转译功能

[✅] 中文或多语言转译为英文

[✅] 标点符号支持

[  ] 添加 Agents，或许可以实现一些屏幕截图，根据上下文做一些输入输出之类的



**如果你也有想法：** 欢迎 Fork 和 PR，如果你在使用当中遇到问题，欢迎提交 Issue。

## 更新日志

#### 2025.07.06
> 1. 新增本地 whisper.cpp 支持，完全本地化处理，无需网络连接
> 2. 添加 LocalWhisperProcessor 处理器，支持本地whisper.cpp推理
> 3. 新增测试脚本 test_local_whisper.py 用于验证本地配置

#### 2025.01.25
> 1. 支持通过环境变量配置恢复原始剪贴板内容，环境变量 `KEEP_ORIGINAL_CLIPBOARD` 默认为 `true` ，设置为 `false` 的时候不恢复

#### 2025.01.19
> 1. 添加对 SiliconFlow 硅基流动托管的转译模型[FunAudioLLM/SenseVoiceSmall](https://docs.siliconflow.cn/api-reference/audio/create-audio-transcriptions) 的支持，自带标点，无需润色，输出结果更快。由 @WEIFENG2333 贡献。

#### 2025.01.16
> 1. 添加标点和优化进行区分，并且默认不优化转译内容
> 2. 去除掉状态展示的动画
> 3. 修复没有重置状态的 Bug，当录音时间小于 1s 时，会触发重置，避免后续的错误

#### 2025.01.15
> 1. 支持 Windows，所有用户需要根据自己的本地环境 pip-compile 
> 2. 采用字节流 buffer 存储录音，不需要存储到本地

#### 2025.01.14
> 1. 支持语音输入结果优化，并更换推荐模型为 `Llama 3.3 70B`，同样免费

#### 2025.01.13
> 1. 支持国内网络，无需申请 Groq API KEY 可以免费使用，Erlich 提供免费代理 API KEY
> 2. 通过环境变量支持将繁体中文转化为简体中文 `.env` ，`CONVERT_TO_SIMPLIFIED=true`，默认开启
> 3. 通过环境变量支持添加标点符号功能 `.env`，`ADD_SYMBOL=true`，默认开启，可以更换模型

#### 2025.01.12
> 1. 增加了一个延迟 0.5s 的触发，方便在一些快捷键需要用到 Option/Alt 按钮时不会被误触
> 2. 重构代码

#### 2025.01.11
> 1. 支持快捷键按下后的状态显示【正在录音、正在转译/翻译、完成】
> 2. 支持多语言语音转换为英文输出

#### 2025.01.10

> 1. 支持基本的快捷键语音转文字输入

## 协议

遵循 MIT 协议