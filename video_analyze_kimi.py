#!/usr/bin/env python3
"""
使用 Kimi Vision 分析视频并生成 Markdown 存档。
用法: python video_analyze_kimi.py <视频路径> [输出md路径]
"""
import os
import sys
import base64
import json
import urllib.request
from pathlib import Path
from dotenv import load_dotenv
import cv2

load_dotenv()

API_KEY = os.getenv("GLM_API_KEY", "").strip()
BASE_URL = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").strip().rstrip("/")
MODEL = "glm-4v-flash"
MAX_FRAMES = 4


def extract_frames(video_path: str, max_frames: int = MAX_FRAMES):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / fps if fps > 0 else 0
    indices = [int(i * total_frames / max_frames) + total_frames // (max_frames * 2) for i in range(max_frames)]
    indices = [min(i, total_frames - 1) for i in indices]
    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        _, buf = cv2.imencode(".jpg", frame)
        b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
        timestamp = idx / fps if fps > 0 else 0
        frames.append((b64, timestamp))
    cap.release()
    return frames, duration, total_frames, fps


def analyze_video(video_path: str, prompt: str) -> str:
    if not API_KEY:
        return "错误: 未找到 KIMI_API_KEY，请检查 .env 文件"
    print(f"[视频] 正在提取帧: {video_path}")
    frames, duration, total_frames, fps = extract_frames(video_path)
    print(f"[信息] 时长: {duration:.1f}s, 总帧数: {total_frames}, FPS: {fps:.2f}, 提取帧数: {len(frames)}")
    content = [{"type": "text", "text": prompt}]
    for b64, ts in frames:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        content.append({"type": "text", "text": f"（视频第 {ts:.1f} 秒画面）"})
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 1024,
        "temperature": 0.7,
    }
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=300)
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        return f"API 错误 (HTTP {e.code}): {err[:1000]}"
    except Exception as e:
        return f"请求异常: {e}"


def main():
    if len(sys.argv) < 2:
        print("用法: python video_analyze_kimi.py <视频路径> [输出md路径]")
        sys.exit(1)
    video_path = sys.argv[1]
    if len(sys.argv) >= 3:
        out_path = sys.argv[2]
    else:
        p = Path(video_path)
        out_path = str(p.with_suffix(".md"))
    prompt = (
        "请作为新媒体脚本分析专家，基于以下视频关键帧，详细分析这个视频案例。\n"
        "请按以下结构输出：\n"
        "1. 视频类型与主题定位\n"
        "2. 整体结构与时长节奏\n"
        "3. 开头钩子设计（前3秒如何抓人）\n"
        "4. 内容叙事与场景转换\n"
        "5. 画面风格与拍摄手法\n"
        "6. 音频、配乐与口播特点（可基于画面推断）\n"
        "7. 字幕、花字与视觉包装\n"
        "8. 结尾与转化引导\n"
        "9. 这个案例的亮点与可复用点\n"
        "10. 可改进建议\n"
        "请尽量详细、具体，便于团队学习复用。"
    )
    result = analyze_video(video_path, prompt)
    from datetime import datetime
    video_name = Path(video_path).name
    md_content = f"""# {Path(video_path).stem}

> 来源视频：`{video_name}`
> 分析时间：{datetime.now().isoformat(timespec='minutes')}
> 分析方式：GLM-4V 关键帧分析

---

{result}

---

*本分析由 AI 根据视频关键帧生成，供团队参考复盘。*
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"\n[完成] 已保存到: {out_path}")


if __name__ == "__main__":
    main()
