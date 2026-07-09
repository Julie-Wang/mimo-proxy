#!/usr/bin/env python3
"""
MiMo-Omni 图片/视频分析工具
用法: python omni_analyzer.py <图片或视频路径> [提示词]
"""
import os
import sys
import base64
import mimetypes
import urllib.request
import json
from pathlib import Path

# 加载 .env 中的 Key
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("MIMO_API_KEY", "").strip()
# Omni endpoint: use MIMO_OMNI_BASE_URL if set, otherwise fall back to MIMO_BASE_URL
BASE_URL = os.getenv("MIMO_OMNI_BASE_URL", os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")).strip().rstrip("/")


def encode_file(filepath: str) -> tuple[str, str]:
    """读取文件并返回 (base64_data, mime_type)"""
    mime, _ = mimetypes.guess_type(filepath)
    if mime is None:
        ext = Path(filepath).suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
            ".webm": "video/webm",
        }
        mime = mime_map.get(ext, "application/octet-stream")

    with open(filepath, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return data, mime


def analyze_media(filepath: str, prompt: str = "请详细描述这张图片/视频的内容。") -> str:
    if not API_KEY:
        return "错误: 未找到 MIMO_API_KEY，请检查 .env 文件"

    if not os.path.exists(filepath):
        return f"错误: 文件不存在: {filepath}"

    b64_data, mime = encode_file(filepath)
    is_video = mime.startswith("video/")
    media_type = "视频" if is_video else "图片"

    print(f"[{media_type}] 正在分析: {filepath} ({mime})")
    print(f"[提示词] {prompt}\n")

    # 构建 OpenAI 兼容的多模态请求
    # 注意: MiMo-Omni 的 vision 端点可能是 /v1/chat/completions
    url = f"{BASE_URL}/v1/chat/completions"

    payload = {
        "model": "mimo-v2-omni",  # 已验证可用的 Omni 模型名
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64_data}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 2048
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        },
        method="POST"
    )

    try:
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"]
        return content
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        return f"API 错误 (HTTP {e.code}): {err_body[:500]}"
    except Exception as e:
        return f"请求异常: {e}"


def main():
    args = sys.argv[1:]
    raw_mode = "--raw" in args
    if raw_mode:
        args.remove("--raw")

    if len(args) < 1:
        print("用法: python omni_analyzer.py [--raw] <图片或视频路径> [提示词]")
        print("示例: python omni_analyzer.py D:\\图片\\截图.png")
        print("示例: python omni_analyzer.py --raw D:\\图片\\截图.png")
        sys.exit(1)

    filepath = args[0]
    prompt = args[1] if len(args) > 1 else "请详细描述这张图片/视频的内容。"

    result = analyze_media(filepath, prompt)
    if raw_mode:
        print(result)
    else:
        print("\n" + "=" * 50)
        print("分析结果:")
        print("=" * 50)
        print(result)


if __name__ == "__main__":
    main()
