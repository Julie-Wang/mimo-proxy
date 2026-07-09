# MiMo Multi-Model Local Proxy
# MiMo 多模型本地代理

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

> **中文**：一个轻量级本地代理网关，将 Obsidian Claudian / Claude Code 等客户端的请求统一转发到 MiMo、Claude、Kimi、GLM、ModelScope DeepSeek 等上游模型，同时避免 API Key 直接暴露在插件配置中。
>
> **English**: A lightweight local proxy gateway that unifies requests from Obsidian Claudian / Claude Code clients to upstream models (MiMo, Claude, Kimi, GLM, ModelScope DeepSeek) without exposing your API keys in plugin settings.

---

## ✨ Features / 功能特性

| Feature / 功能 | Description / 说明 |
|---|---|
| 🔒 API Key Protection / Key 隔离 | 真实 API Key 只保存在本地 `.env`，插件只配置代理地址 / Real API keys stay in local `.env`; plugins only know the proxy address. |
| 🚀 Multi-Model Routing / 多模型路由 | 根据请求中的 `model` 字段自动路由到 MiMo / Claude / Kimi / GLM / ModelScope / 自动路由 based on the `model` field. |
| 🔧 Protocol Adaptation / 协议适配 | 自动修补 Anthropic / OpenAI 响应格式差异 / Auto-patches differences between Anthropic and OpenAI response formats. |
| 📹 Video Analysis / 视频分析 | 内置 `batch_video_analyzer.py` 与 `omni_analyzer.py`，基于 MiMo-V2-Omni 批量分析视频质量。 / Built-in video analysis tools powered by MiMo-V2-Omni. |
| 📊 Streaming Support / 流式支持 | 支持 SSE 流式转发，适配 Claudian 长回复场景 / Supports SSE streaming for long-form responses in Claudian. |
| 🧪 Test Suite / 测试脚本 | 提供多个 `test_*.py` 脚本，方便验证代理与上游连通性。 / Includes `test_*.py` scripts for connectivity verification. |

---

## 🏗️ Architecture / 架构

```
┌─────────────────┐      ┌──────────────────────┐      ┌─────────────────────┐
│  Obsidian       │      │  MiMo Local Proxy    │      │  Upstream APIs      │
│  Claudian /     │ ──►  │  http://127.0.0.1:8787 │ ──► │  MiMo / Claude /    │
│  Claude Code    │      │  (FastAPI + httpx)   │      │  Kimi / GLM /       │
└─────────────────┘      └──────────────────────┘      │  ModelScope         │
                                                       └─────────────────────┘
```

Routing rules / 路由规则 (based on `model` in request body):

| Model Keyword / 模型关键字 | Upstream / 上游 | Protocol / 协议 |
|---|---|---|
| `claude*` | Anthropic / Claude 中转 | Anthropic Messages |
| `mimo*` | Xiaomi MiMo | Anthropic-compatible |
| `kimi*` | Moonshot Kimi | OpenAI-compatible |
| `glm*` | Zhipu GLM | OpenAI-compatible |
| `deepseek*` | ModelScope DeepSeek | OpenAI-compatible |
| others / 其他 | Default to MiMo / 默认走 MiMo | — |

---

## 📦 Installation / 安装

```bash
# 1. Clone or download this repository
# 1. 克隆或下载本仓库
git clone https://github.com/Julie-Wang/mimo-proxy.git
cd mimo-proxy

# 2. Install dependencies
# 2. 安装依赖
pip install -r requirements.txt

# 3. Copy example environment file
# 3. 复制环境变量示例文件
cp .env.example .env

# 4. Edit .env with your real API keys
# 4. 编辑 .env 填入真实 API Key
```

> **Windows users / Windows 用户**：也可以直接双击 `start-proxy.bat` 或在 PowerShell 执行 `\.start.ps1`。

---

## ⚙️ Configuration / 配置

Edit `.env`:

```bash
# Required / 必需
MIMO_API_KEY=sk-your-mimo-api-key
MIMO_BASE_URL=https://api.xiaomimimo.com/v1

# Optional / 可选
MIMO_OMNI_BASE_URL=https://api.xiaomimimo.com/v1
CLAUDE_API_KEY=sk-your-anthropic-key
KIMI_API_KEY=sk-your-kimi-key
GLM_API_KEY=sk-your-glm-key
MODELSCOPE_API_TOKEN=your-modelscope-token

# Proxy host / 代理监听地址
PROXY_HOST=127.0.0.1
PROXY_PORT=8787
```

**⚠️ Never commit `.env` to Git / 切勿将 `.env` 提交到 Git。**

---

## 🚀 Usage / 使用

### Start the Proxy / 启动代理

```powershell
# Windows PowerShell
.\start.ps1

# Or manually / 或手动启动
python main.py
```

You should see / 看到如下输出即成功：

```
🚀 MiMo Local Proxy 启动中...
   监听地址: http://127.0.0.1:8787
   目标上游: https://api.xiaomimimo.com/v1
   健康检查: http://127.0.0.1:8787/health
```

### Connect Claudian (Obsidian) / 接入 Claudian

1. Open Obsidian → Settings → **Claudian**
2. Enable **Codex**
3. In Codex **Environment**, set / 在 Codex **Environment** 中填写：

```bash
OPENAI_API_KEY=local-proxy
OPENAI_BASE_URL=http://127.0.0.1:8787
OPENAI_MODEL=mimo-v2.5-pro
```

> `OPENAI_API_KEY` can be any value; the proxy ignores it and injects your real MiMo key.
> `OPENAI_API_KEY` 可以填任意值，代理会忽略它并自动换上真实的 MiMo Key。

4. Switch Provider from **Claude** to **Codex** in the chat window.
5. Start chatting / 开始对话。

---

## 🎬 Video Analysis / 视频分析

### Single image or video / 单张图片或视频

```bash
python omni_analyzer.py <path/to/media> [prompt]
```

### Batch video quality report / 批量视频质量报告

```bash
python batch_video_analyzer.py --input "D:\Videos" --output "report.md"
```

This will scan all video files under the input directory and generate a Markdown report with scores for clarity, color, stability, exposure, composition, audio, and overall quality.

该脚本会扫描输入目录下的所有视频，并生成包含清晰度、色彩、稳定性、曝光、构图、音频、综合评分等维度的 Markdown 报告。

---

## 🧪 Testing / 测试

```bash
# Test local gateway routing / 测试网关路由
python test_gateway.py

# Test local gateway streaming / 测试网关流式响应
python test_gateway_stream.py

# Test response patching / 测试响应修补
python test_patch.py
```

---

## 📁 Project Structure / 项目结构

```
mimo-proxy/
├── main.py                      # FastAPI proxy gateway / 代理网关主程序
├── batch_video_analyzer.py      # Batch video quality analysis / 批量视频质量分析
├── omni_analyzer.py             # Single image/video analysis / 单图/视频分析
├── video_analyze_kimi.py        # Video analysis via GLM vision / 基于 GLM 视觉模型的视频分析
├── requirements.txt             # Python dependencies / Python 依赖
├── .env.example                 # Environment variables template / 环境变量模板
├── start.ps1                    # PowerShell startup script / PowerShell 启动脚本
├── start-proxy.bat              # Windows batch startup script / Windows 批处理启动脚本
├── test_*.py                    # Test scripts / 测试脚本
├── README.md                    # This file / 本文件
└── LICENSE                      # MIT License / MIT 许可证
```

---

## 🤝 Contributing / 贡献

Issues and pull requests are welcome. Please make sure not to commit any API keys or personal paths.

欢迎提交 Issue 和 Pull Request。请勿提交任何 API Key 或个人路径。

---

## 📄 License / 许可证

This project is licensed under the [MIT License](./LICENSE).

本项目采用 [MIT 许可证](./LICENSE)。

---

## 🙏 Acknowledgments / 致谢

- Inspired by the need to safely bridge Obsidian Claudian with Chinese LLM providers.
- Powered by [FastAPI](https://fastapi.tiangolo.com/), [httpx](https://www.python-httpx.org/), and [python-dotenv](https://saurabh-kumar.com/python-dotenv/).
