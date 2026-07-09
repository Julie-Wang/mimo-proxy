"""
批量视频质量分析脚本
====================
调用 MiMo-V2-Omni 模型分析视频质量，输出评分报告。

用法：
    python batch_video_analyzer.py --input "D:\Videos" --output "report.md"

支持格式：mp4, mov, avi, mkv, webm, flv, wmv
"""

import os
import sys
import json
import base64
import time
import argparse
from pathlib import Path
from datetime import datetime

import httpx

# ==================== 配置 ====================

PROXY_URL = "http://127.0.0.1:8787/anthropic/v1/messages"
API_KEY = "local-proxy"
MODEL = "mimo-v2-omni"
MAX_TOKENS = 4096

# 视频文件扩展名
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v", ".3gp"}

# 提示词模板
PROMPT_TEMPLATE = """请对以下视频进行全面的质量分析评价，按以下维度打分（1-10分）并给出详细说明：

## 评价维度
1. **画面清晰度**：分辨率、锐度、噪点控制
2. **色彩表现**：色彩准确度、饱和度、对比度
3. **稳定性**：画面抖动、运动模糊
4. **曝光控制**：过曝/欠曝、动态范围
5. **构图质量**：取景、主体突出、背景处理
6. **音频质量**（如有）：清晰度、噪音、音量平衡
7. **综合评分**：整体观感

## 输出格式
请按以下 JSON 格式输出（不要包含 markdown 代码块标记）：

{
  "filename": "视频文件名",
  "duration_seconds": 估计时长,
  "scores": {
    "clarity": 8.5,
    "color": 7.0,
    "stability": 9.0,
    "exposure": 6.5,
    "composition": 7.5,
    "audio": 8.0,
    "overall": 7.8
  },
  "pros": ["优点1", "优点2"],
  "cons": ["不足1", "不足2"],
  "suggestions": ["改进建议1", "改进建议2"],
  "summary": "总体评价摘要（100字以内）"
}"""


# ==================== 工具函数 ====================

def find_videos(input_dir: str):
    """扫描目录中的所有视频文件"""
    input_path = Path(input_dir)
    videos = []
    for ext in VIDEO_EXTENSIONS:
        videos.extend(input_path.rglob(f"*{ext}"))
        videos.extend(input_path.rglob(f"*{ext.upper()}"))
    # 去重并排序
    seen = set()
    unique_videos = []
    for v in videos:
        if v not in seen:
            seen.add(v)
            unique_videos.append(v)
    return sorted(unique_videos)


def encode_video(video_path: Path) -> tuple[str, int]:
    """将视频文件转为 base64，返回 (base64_string, file_size_bytes)"""
    with open(video_path, "rb") as f:
        data = f.read()
    size_mb = len(data) / (1024 * 1024)
    b64 = base64.b64encode(data).decode("utf-8")
    return b64, len(data), size_mb


def call_mimo_omni(video_b64: str, media_type: str, filename: str) -> dict:
    """调用 MiMo-V2-Omni API 分析视频"""
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT_TEMPLATE},
                    {
                        "type": "video",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": video_b64
                        }
                    }
                ]
            }
        ]
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # 非流式请求（分析视频用非流式更稳定）
    with httpx.Client(timeout=300.0) as client:
        resp = client.post(PROXY_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def extract_json_from_text(text: str) -> dict:
    """从模型返回的文本中提取 JSON"""
    # 先尝试直接解析
    text = text.strip()
    if text.startswith("```"):
        # 去掉 markdown 代码块
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试找花括号包裹的内容
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass
        raise


def parse_response(response: dict, filename: str) -> dict:
    """解析 API 响应，提取分析结果"""
    result = {
        "filename": filename,
        "raw_response": "",
        "parsed": None,
        "error": None
    }

    try:
        content_blocks = response.get("content", [])
        text_parts = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        full_text = "\n".join(text_parts)
        result["raw_response"] = full_text[:2000]  # 限制长度

        if full_text:
            parsed = extract_json_from_text(full_text)
            result["parsed"] = parsed
    except Exception as e:
        result["error"] = str(e)

    return result


def generate_report(results: list[dict], output_path: Path):
    """生成 Markdown 报告"""
    lines = []
    lines.append("# 视频质量分析报告")
    lines.append(f"\n> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 分析模型：MiMo-V2-Omni")
    lines.append(f"> 视频总数：{len(results)}")
    lines.append("")

    # 汇总表格
    lines.append("## 汇总评分")
    lines.append("")
    lines.append("| 文件名 | 综合评分 | 清晰度 | 色彩 | 稳定性 | 曝光 | 构图 | 音频 | 时长(秒) |")
    lines.append("|--------|----------|--------|------|--------|------|------|------|----------|")

    for r in results:
        fname = r["filename"]
        p = r.get("parsed", {})
        scores = p.get("scores", {}) if p else {}
        duration = p.get("duration_seconds", "-") if p else "-"
        line = f"| {fname} | {scores.get('overall', '-')} | {scores.get('clarity', '-')} | {scores.get('color', '-')} | {scores.get('stability', '-')} | {scores.get('exposure', '-')} | {scores.get('composition', '-')} | {scores.get('audio', '-')} | {duration} |"
        lines.append(line)

    lines.append("")

    # 详细分析
    lines.append("## 详细分析")
    lines.append("")

    for r in results:
        fname = r["filename"]
        p = r.get("parsed")
        lines.append(f"### {fname}")
        lines.append("")

        if r.get("error"):
            lines.append(f"**❌ 解析失败**：{r['error']}")
            lines.append(f"\n原始响应：\n```\n{r['raw_response'][:500]}\n```")
        elif p:
            scores = p.get("scores", {})
            lines.append(f"**综合评分**：⭐ {scores.get('overall', '-')} / 10")
            lines.append("")
            lines.append("| 维度 | 评分 |")
            lines.append("|------|------|")
            lines.append(f"| 画面清晰度 | {scores.get('clarity', '-')} |")
            lines.append(f"| 色彩表现 | {scores.get('color', '-')} |")
            lines.append(f"| 稳定性 | {scores.get('stability', '-')} |")
            lines.append(f"| 曝光控制 | {scores.get('exposure', '-')} |")
            lines.append(f"| 构图质量 | {scores.get('composition', '-')} |")
            lines.append(f"| 音频质量 | {scores.get('audio', '-')} |")
            lines.append("")

            pros = p.get("pros", [])
            if pros:
                lines.append("**优点**：")
                for pro in pros:
                    lines.append(f"- ✅ {pro}")
                lines.append("")

            cons = p.get("cons", [])
            if cons:
                lines.append("**不足**：")
                for con in cons:
                    lines.append(f"- ⚠️ {con}")
                lines.append("")

            suggestions = p.get("suggestions", [])
            if suggestions:
                lines.append("**改进建议**：")
                for s in suggestions:
                    lines.append(f"- 💡 {s}")
                lines.append("")

            summary = p.get("summary", "")
            if summary:
                lines.append(f"**总结**：{summary}")
                lines.append("")
        else:
            lines.append("**⚠️ 未解析到有效结果**")
            lines.append(f"\n原始响应：\n```\n{r['raw_response'][:500]}\n```")

        lines.append("---")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ 报告已保存：{output_path}")


# ==================== 主程序 ====================

def main():
    parser = argparse.ArgumentParser(description="批量视频质量分析")
    parser.add_argument("--input", "-i", required=True, help="视频文件所在目录")
    parser.add_argument("--output", "-o", default="video_report.md", help="输出报告路径")
    parser.add_argument("--limit", "-l", type=int, default=0, help="最多处理多少个视频（0=全部）")
    parser.add_argument("--skip-large", "-s", type=float, default=50.0, help="跳过大于多少 MB 的视频（默认50MB）")
    args = parser.parse_args()

    input_dir = args.input
    output_path = Path(args.output)

    if not os.path.isdir(input_dir):
        print(f"❌ 目录不存在：{input_dir}")
        sys.exit(1)

    # 确保代理已启动
    try:
        httpx.get("http://127.0.0.1:8787/health", timeout=5.0)
    except Exception:
        print("⚠️ 警告：代理似乎未启动，请先运行 python main.py")
        confirm = input("是否继续？(y/N): ")
        if confirm.lower() != "y":
            sys.exit(1)

    # 发现视频
    videos = find_videos(input_dir)
    if not videos:
        print(f"❌ 未在 {input_dir} 中找到视频文件")
        sys.exit(1)

    if args.limit > 0:
        videos = videos[:args.limit]

    print(f"\n📁 发现 {len(videos)} 个视频文件")
    print(f"📄 输出报告：{output_path.absolute()}")
    print(f"📏 大小限制：跳过 > {args.skip_large} MB 的视频")
    print("=" * 50)

    results = []

    for idx, video_path in enumerate(videos, 1):
        print(f"\n[{idx}/{len(videos)}] 处理：{video_path.name}")

        try:
            # 编码视频
            video_b64, size_bytes, size_mb = encode_video(video_path)
            print(f"   大小：{size_mb:.1f} MB")

            if size_mb > args.skip_large:
                print(f"   ⏭️ 跳过（超过 {args.skip_large} MB）")
                results.append({
                    "filename": video_path.name,
                    "error": f"文件过大（{size_mb:.1f} MB > {args.skip_large} MB）",
                    "parsed": None,
                    "raw_response": ""
                })
                continue

            # 确定 media_type
            ext = video_path.suffix.lower()
            media_type_map = {
                ".mp4": "video/mp4",
                ".mov": "video/quicktime",
                ".avi": "video/x-msvideo",
                ".mkv": "video/x-matroska",
                ".webm": "video/webm",
                ".flv": "video/x-flv",
                ".wmv": "video/x-ms-wmv",
                ".m4v": "video/mp4",
                ".3gp": "video/3gpp",
            }
            media_type = media_type_map.get(ext, "video/mp4")

            # 调用 API
            print(f"   🚀 发送请求...")
            start = time.time()
            response = call_mimo_omni(video_b64, media_type, video_path.name)
            elapsed = time.time() - start
            print(f"   ⏱️ 耗时：{elapsed:.1f} 秒")

            # 解析结果
            result = parse_response(response, video_path.name)
            if result.get("parsed"):
                overall = result["parsed"].get("scores", {}).get("overall", "-")
                print(f"   ✅ 综合评分：{overall}")
            elif result.get("error"):
                print(f"   ⚠️ 解析失败：{result['error']}")
            else:
                print(f"   ⚠️ 未返回有效结果")

            results.append(result)

        except Exception as e:
            print(f"   ❌ 错误：{e}")
            results.append({
                "filename": video_path.name,
                "error": str(e),
                "parsed": None,
                "raw_response": ""
            })

    # 生成报告
    print("\n" + "=" * 50)
    print("📊 生成报告中...")
    generate_report(results, output_path)

    # 统计
    success = sum(1 for r in results if r.get("parsed"))
    failed = len(results) - success
    print(f"\n📈 统计：成功 {success} / 失败 {failed} / 总计 {len(results)}")


if __name__ == "__main__":
    main()
