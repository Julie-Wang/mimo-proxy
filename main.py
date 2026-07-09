"""
Multi-Model Local Proxy
=======================
统一网关：Claudian → http://localhost:8787 → MiMo / Claude中转站 / 魔搭DeepSeek

路由规则（根据请求 body 中的 model 字段）：
- model 包含 "claude" → 转发到 Claude 中转站 (Anthropic协议)
- model 包含 "mimo"   → 转发到 MiMo 官方 (Anthropic协议)
- model 包含 "deepseek" → 魔搭 ModelScope (OpenAI协议，需转换)
- 其他/空               → 默认走 MiMo（向后兼容）
"""

import os
import json
import time
import uuid
from typing import AsyncGenerator
from dotenv import load_dotenv
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware

# 请求日志文件
LOG_FILE = os.path.join(os.path.dirname(__file__), "proxy_requests.log")


def log_request(
    method: str,
    path: str,
    headers: dict,
    body: bytes,
    status: int = None,
    error: str = None,
    upstream: str = None,
):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    safe_headers = {
        k: v for k, v in headers.items() if k.lower() in ("content-type", "user-agent")
    }
    header_str = json.dumps(safe_headers, ensure_ascii=False)
    body_len = len(body) if body else 0
    status_str = f" | STATUS: {status}" if status else ""
    error_str = f" | ERROR: {error}" if error else ""
    upstream_str = f" | UPSTREAM: {upstream}" if upstream else ""
    line = (
        f"[{ts}] {method} /{path}{upstream_str} | headers: {header_str} | body_len: {body_len}"
        f"{status_str}{error_str}\n"
    )
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
            # 记录请求 body 便于调试（限制长度）
            if body and status is None:
                try:
                    body_text = body.decode("utf-8", errors="replace")
                    body_json = json.loads(body_text)
                    # 只记录 messages 和 model 字段
                    debug_info = {
                        "model": body_json.get("model"),
                        "thinking": body_json.get("thinking"),
                        "messages_preview": []
                    }
                    for msg in body_json.get("messages", [])[-3:]:
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            types = [c.get("type") for c in content]
                            debug_info["messages_preview"].append({
                                "role": msg.get("role"),
                                "content_types": types
                            })
                            if "video" in types:
                                print(f"[VIDEO_DETECTED] role={msg.get('role')} types={types}", flush=True)
                        else:
                            debug_info["messages_preview"].append({
                                "role": msg.get("role"),
                                "content_preview": str(content)[:200]
                            })
                    f.write(f"  [DEBUG_REQ] {json.dumps(debug_info, ensure_ascii=False)}\n")
                except Exception:
                    pass
    except Exception:
        pass


# 加载 .env 配置
load_dotenv()

MIMO_API_KEY = os.getenv("MIMO_API_KEY", "").strip()
MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "").strip().rstrip("/")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "").strip()
CLAUDE_BASE_URL = os.getenv("CLAUDE_BASE_URL", "https://api.anthropic.com").strip().rstrip("/")
KIMI_API_KEY = os.getenv("KIMI_API_KEY", "").strip()
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1").strip().rstrip("/")
MODELSCOPE_API_TOKEN = os.getenv("MODELSCOPE_API_TOKEN", "").strip()
MODELSCOPE_BASE_URL = os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1").strip().rstrip("/")
GLM_API_KEY = os.getenv("GLM_API_KEY", "").strip()
GLM_BASE_URL = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").strip().rstrip("/")
PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1").strip()
PROXY_PORT = int(os.getenv("PROXY_PORT", "8787"))

if not MIMO_API_KEY:
    raise RuntimeError("MIMO_API_KEY 未设置，请在 .env 文件中配置")
# CLAUDE 配置为可选：留空则禁用 Claude 路由，填了官方 Key 即启用

# 支持的模型列表（用于 /v1/models）
SUPPORTED_MODELS = [
    # MiMo 核心模型
    {"id": "mimo-v2.5", "object": "model", "owned_by": "xiaomi"},
    {"id": "mimo-v2.5-pro", "object": "model", "owned_by": "xiaomi"},
    {"id": "mimo-v2-flash", "object": "model", "owned_by": "xiaomi"},
    # MiMo 多模态 / TTS
    {"id": "mimo-v2-omni", "object": "model", "owned_by": "xiaomi"},
    {"id": "mimo-v2-tts", "object": "model", "owned_by": "xiaomi"},
    {"id": "mimo-v2.5-tts", "object": "model", "owned_by": "xiaomi"},
    {"id": "mimo-v2.5-tts-voicedesign", "object": "model", "owned_by": "xiaomi"},

    # Claude 模型（未配置 Key 时自动回退到 MiMo）
    {"id": "claude-haiku-4-5", "object": "model", "owned_by": "anthropic"},
    {"id": "claude-haiku-4-5-20250929", "object": "model", "owned_by": "anthropic"},
    {"id": "claude-sonnet-4-5", "object": "model", "owned_by": "anthropic"},
    {"id": "claude-sonnet-4-5-20250929", "object": "model", "owned_by": "anthropic"},
    {"id": "claude-sonnet-4-6", "object": "model", "owned_by": "anthropic"},
    {"id": "claude-sonnet-4-6-20250929", "object": "model", "owned_by": "anthropic"},
    {"id": "claude-opus-4-5", "object": "model", "owned_by": "anthropic"},
    {"id": "claude-opus-4-5-20250929", "object": "model", "owned_by": "anthropic"},
    {"id": "claude-opus-4-6", "object": "model", "owned_by": "anthropic"},
    {"id": "claude-opus-4-6-20250929", "object": "model", "owned_by": "anthropic"},

    # 其他上游
    {"id": "kimi-k2-0711", "object": "model", "owned_by": "moonshot"},
    {"id": "deepseek-ai/DeepSeek-V3.2", "object": "model", "owned_by": "deepseek"},
    {"id": "deepseek-ai/DeepSeek-R1-0528", "object": "model", "owned_by": "deepseek"},

    # GLM 上游
    {"id": "glm-4-flash", "object": "model", "owned_by": "zhipu"},
    {"id": "glm-4-air", "object": "model", "owned_by": "zhipu"},
    {"id": "glm-4-plus", "object": "model", "owned_by": "zhipu"},
]


def _ensure_usage(obj: dict) -> bool:
    """确保对象中的 usage 字段完整，返回是否修改"""
    modified = False
    if "usage" not in obj or obj["usage"] is None:
        obj["usage"] = {}
        modified = True
    usage = obj.get("usage", {})
    if isinstance(usage, dict):
        if "input_tokens" not in usage:
            usage["input_tokens"] = 0
            modified = True
        if "output_tokens" not in usage:
            usage["output_tokens"] = 0
            modified = True
    return modified


def _patch_thinking_signature(obj: dict) -> bool:
    """
    给 MiMo 返回的 thinking 块补上缺少的 signature 字段。
    Claude Code 要求 thinking 块必须有 signature，否则解析失败。
    返回是否修改。
    """
    modified = False
    if not isinstance(obj, dict):
        return modified

    # 1) content_block_start / content_block 对象
    if obj.get("type") == "thinking" and "signature" not in obj:
        obj["signature"] = ""
        modified = True

    # 2) content 数组（非流式响应顶层）
    if isinstance(obj.get("content"), list):
        for block in obj["content"]:
            if isinstance(block, dict) and block.get("type") == "thinking" and "signature" not in block:
                block["signature"] = ""
                modified = True

    return modified


def patch_anthropic_json(body: bytes) -> bytes:
    """修补 Anthropic 响应，补充缺失的 usage 字段 + thinking→text 转换"""
    if not body:
        return body
    try:
        text = body.decode("utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            return body
        modified = False

        # 顶层 usage
        modified |= _ensure_usage(data)

        # message 对象中的 usage
        if isinstance(data.get("message"), dict):
            modified |= _ensure_usage(data["message"])

        # delta 对象中的 usage (message_delta 事件)
        if isinstance(data.get("delta"), dict) and "usage" in data:
            modified |= _ensure_usage(data)

        # content_block 中的 usage (如果有)
        if isinstance(data.get("content_block"), dict):
            modified |= _ensure_usage(data["content_block"])

        # 给 MiMo 的 thinking 块补上缺少的 signature（Claude Code 要求必须有）
        modified |= _patch_thinking_signature(data)
        if isinstance(data.get("message"), dict):
            modified |= _patch_thinking_signature(data["message"])

        if modified:
            return json.dumps(data, ensure_ascii=False).encode("utf-8")
    except Exception:
        pass
    return body


def patch_anthropic_sse_line(line: bytes) -> bytes:
    """修补 SSE 流中的 data: 行，补充缺失的 usage 字段 + thinking→text 转换"""
    if not line.startswith(b"data: "):
        return line
    try:
        json_str = line[6:].decode("utf-8")  # 去掉 "data: "
        data = json.loads(json_str)
        if not isinstance(data, dict):
            return line
        modified = False
        event_type = data.get("type", "")

        # message_start: usage 在 message 内部
        if event_type == "message_start" and isinstance(data.get("message"), dict):
            modified |= _ensure_usage(data["message"])

        # message_delta: usage 在 delta 内部（关键！Claudian 读的是 delta.usage）
        if event_type == "message_delta" and isinstance(data.get("delta"), dict):
            delta = data["delta"]
            if "usage" not in delta or delta["usage"] is None:
                delta["usage"] = {}
                modified = True
            usage = delta.get("usage", {})
            if isinstance(usage, dict):
                if "input_tokens" not in usage:
                    usage["input_tokens"] = 0
                    modified = True
                if "output_tokens" not in usage:
                    usage["output_tokens"] = 0
                    modified = True

        # 兜底：顶层 usage（某些中转站可能在非标准位置放 usage）
        if "usage" in data:
            modified |= _ensure_usage(data)

        # 给 MiMo 的 thinking 块补上缺少的 signature（流式）
        modified |= _patch_thinking_signature(data)
        if isinstance(data.get("message"), dict):
            modified |= _patch_thinking_signature(data["message"])
        if isinstance(data.get("content_block"), dict):
            modified |= _patch_thinking_signature(data["content_block"])

        if modified:
            new_json = json.dumps(data, ensure_ascii=False)
            return f"data: {new_json}".encode("utf-8")
    except Exception:
        pass
    return line


def patch_openai_json(body: bytes) -> bytes:
    """修补 OpenAI 格式响应：将 MiMo 的 reasoning_content 复制到 content"""
    if not body:
        return body
    try:
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, dict):
            return body
        modified = False
        choices = data.get("choices", [])
        if choices and isinstance(choices[0], dict):
            choice = choices[0]
            message = choice.get("message", {})
            if isinstance(message, dict):
                content = message.get("content")
                reasoning = message.get("reasoning_content")
                # content 为 None / 空字符串 / 缺失，且 reasoning_content 存在时复制
                if (content is None or (isinstance(content, str) and content.strip() == "")) and reasoning:
                    message["content"] = reasoning
                    modified = True
            # 兜底：某些接口 reasoning_content 可能直接在 choice 上
            if not modified:
                reasoning = choice.get("reasoning_content")
                content = choice.get("message", {}).get("content")
                if (content is None or (isinstance(content, str) and content.strip() == "")) and reasoning:
                    choice["message"]["content"] = reasoning
                    modified = True
        if modified:
            return json.dumps(data, ensure_ascii=False).encode("utf-8")
    except Exception:
        pass
    return body


def patch_openai_sse_line(line: bytes) -> bytes:
    """修补 OpenAI SSE chunk：将 MiMo 的 reasoning_content 复制到 content"""
    if not line.startswith(b"data: "):
        return line
    if line.strip() == b"data: [DONE]":
        return line
    # 保留原始行尾换行符（\n 或 \r\n）
    trailing = b""
    if line.endswith(b"\r\n"):
        trailing = b"\r\n"
    elif line.endswith(b"\n"):
        trailing = b"\n"
    try:
        # 去掉 data: 前缀和末尾空白
        payload = line[6:].strip()
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            return line
        modified = False
        choices = data.get("choices", [])
        if choices and isinstance(choices[0], dict):
            delta = choices[0].get("delta", {})
            if isinstance(delta, dict):
                content = delta.get("content")
                reasoning = delta.get("reasoning_content")
                if (content is None or (isinstance(content, str) and content.strip() == "")) and reasoning:
                    delta["content"] = reasoning
                    modified = True
        if modified:
            return f"data: {json.dumps(data, ensure_ascii=False)}".encode("utf-8") + trailing
    except Exception:
        pass
    return line


# ==================== Anthropic ↔ OpenAI 协议转换 ====================

def anthropic_to_openai_request(body: dict, model_id: str) -> dict:
    """
    将 Anthropic Messages API 请求转换为 OpenAI Chat Completions API 请求
    """
    messages = []

    # 处理 system 消息
    system_content = body.get("system", "")
    if system_content:
        if isinstance(system_content, str):
            messages.append({"role": "system", "content": system_content})
        elif isinstance(system_content, list):
            texts = [item.get("text", "") for item in system_content if item.get("type") == "text"]
            if texts:
                messages.append({"role": "system", "content": "\n".join(texts)})

    # 转换 messages
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            # 处理多模态 content（简单文本提取，魔搭不一定全支持）
            parts = []
            for item in content:
                if item.get("type") == "text":
                    parts.append({"type": "text", "text": item.get("text", "")})
                elif item.get("type") == "image":
                    source = item.get("source", {})
                    image_url = source.get("data", "")
                    if source.get("type") == "base64" and not image_url.startswith("data:"):
                        media_type = source.get("media_type", "image/png")
                        image_url = f"data:{media_type};base64,{image_url}"
                    parts.append({"type": "image_url", "image_url": {"url": image_url}})
            if parts:
                messages.append({"role": role, "content": parts})
            else:
                messages.append({"role": role, "content": ""})

    result = {
        "model": model_id,
        "messages": messages,
        "stream": body.get("stream", False),
    }

    if "max_tokens" in body:
        result["max_tokens"] = body["max_tokens"]
    if "temperature" in body:
        result["temperature"] = body["temperature"]
    if "top_p" in body:
        result["top_p"] = body["top_p"]

    return result


def openai_to_anthropic_response(openai_resp: dict, model_id: str) -> dict:
    """
    将 OpenAI Chat Completions 响应转换为 Anthropic Messages API 响应
    """
    choice = openai_resp.get("choices", [{}])[0]
    message = choice.get("message", {})
    content_text = message.get("content", "") or ""
    # 如果 content 为空但有 reasoning_content，用 reasoning_content 兜底
    reasoning = message.get("reasoning_content")
    if (content_text is None or (isinstance(content_text, str) and content_text.strip() == "")) and reasoning:
        content_text = reasoning

    usage = openai_resp.get("usage", {})

    return {
        "id": openai_resp.get("id", f"msg_{uuid.uuid4().hex[:16]}"),
        "type": "message",
        "role": "assistant",
        "model": model_id,
        "content": [{"type": "text", "text": content_text or ""}],
        "stop_reason": "end_turn" if choice.get("finish_reason") == "stop" else choice.get("finish_reason"),
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }
    }


async def openai_stream_to_anthropic_sse(openai_stream, model_id: str):
    """
    将 OpenAI SSE 流转换为 Anthropic SSE 流
    """
    message_id = f"msg_{uuid.uuid4().hex[:16]}"

    # message_start
    yield f"event: message_start\n".encode("utf-8")
    yield f"data: {json.dumps({'type':'message_start','message':{'id':message_id,'type':'message','role':'assistant','content':[],'model':model_id}}, ensure_ascii=False)}\n\n".encode("utf-8")

    # content_block_start
    yield f"event: content_block_start\n".encode("utf-8")
    yield f"data: {json.dumps({'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}}, ensure_ascii=False)}\n\n".encode("utf-8")

    output_tokens = 0
    finished = False

    async for chunk in openai_stream:
        chunk = chunk.strip()
        if not chunk:
            continue

        # 处理 [DONE] 标记
        if chunk == b"data: [DONE]":
            finished = True
            break

        if chunk.startswith(b"data: "):
            try:
                data = json.loads(chunk[6:].decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    # 如果 content 为空但有 reasoning_content，用 reasoning_content 兜底
                    reasoning = delta.get("reasoning_content")
                    if (content is None or (isinstance(content, str) and content.strip() == "")) and reasoning:
                        content = reasoning
                    if content:
                        output_tokens += max(len(content) // 4, 1)  # 粗略估算 token 数
                        yield f"event: content_block_delta\n".encode("utf-8")
                        yield f"data: {json.dumps({'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':content}}, ensure_ascii=False)}\n\n".encode("utf-8")

                    finish_reason = choices[0].get("finish_reason")
                    if finish_reason:
                        finished = True
                        break
            except Exception:
                pass

    # content_block_stop
    yield f"event: content_block_stop\n".encode("utf-8")
    yield f"data: {json.dumps({'type':'content_block_stop','index':0}, ensure_ascii=False)}\n\n".encode("utf-8")

    # message_delta
    stop_reason = "end_turn"
    yield f"event: message_delta\n".encode("utf-8")
    yield f"data: {json.dumps({'type':'message_delta','delta':{'stop_reason':stop_reason,'stop_sequence':None},'usage':{'output_tokens':output_tokens}}, ensure_ascii=False)}\n\n".encode("utf-8")

    # message_stop
    yield f"event: message_stop\n".encode("utf-8")
    yield f"data: {json.dumps({'type':'message_stop'}, ensure_ascii=False)}\n\n".encode("utf-8")


# ==================== 路由 & 代理 ====================

def resolve_upstream(body_bytes: bytes, path: str) -> tuple[str, str, str, str, bool]:
    """
    根据请求决定使用哪个上游。
    返回: (上游名称, base_url, api_key, path_prefix, needs_conversion)
    path_prefix: 附加在 base_url 和 v1/messages 之间的路径段，如 'anthropic'
    needs_conversion: 是否需要 Anthropic ↔ OpenAI 协议转换
    """
    model = ""
    if body_bytes:
        try:
            data = json.loads(body_bytes)
            model = data.get("model", "").lower()
        except Exception:
            pass

    # 判断请求格式：OpenAI 协议路径特征是 chat/completions
    is_openai_path = "chat/completions" in path

    # ── 路由表：关键词 → 上游，顺序即优先级 ──────────────────────────
    ROUTES = [
        (["glm", "chatglm"],          "glm"),
        (["kimi", "moonshot"],        "kimi"),
        (["deepseek"],                "modelscope"),
        (["mimo"],                    "mimo"),
        (["claude", "haiku", "sonnet", "opus"], "claude"),
    ]

    target = None
    for patterns, upstream in ROUTES:
        if any(p in model for p in patterns):
            target = upstream
            break

    # Claude 系列无官方 key → 降级到魔搭或 MiMo
    if target == "claude" and not CLAUDE_API_KEY:
        target = "modelscope" if MODELSCOPE_API_TOKEN else "mimo"

    # 无匹配 → fallback MiMo
    if target is None:
        target = "mimo"

    # ── 执行路由 ──────────────────────────────────────────────────────
    if target == "glm":
        if not GLM_API_KEY:
            raise HTTPException(status_code=503, detail="GLM 未配置：请设置 GLM_API_KEY")
        return "glm", GLM_BASE_URL, GLM_API_KEY, "", not is_openai_path

    if target == "kimi":
        if not KIMI_API_KEY:
            raise HTTPException(status_code=503, detail="Kimi 未配置：请设置 KIMI_API_KEY")
        return "kimi", KIMI_BASE_URL, KIMI_API_KEY, "", not is_openai_path

    if target == "modelscope":
        if not MODELSCOPE_API_TOKEN:
            raise HTTPException(status_code=503, detail="魔搭未配置：请设置 MODELSCOPE_API_TOKEN")
        return "modelscope", MODELSCOPE_BASE_URL, MODELSCOPE_API_TOKEN, "", not is_openai_path

    if target == "claude":
        return "claude", CLAUDE_BASE_URL, CLAUDE_API_KEY, "", False

    # MiMo（含显式 mimo 和 fallback）
    return "mimo", MIMO_BASE_URL, MIMO_API_KEY, "anthropic", False


app = FastAPI(title="Multi-Model Local Proxy", version="2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "app://obsidian.md",
        "http://127.0.0.1",
        "http://localhost",
        "https://localhost",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "upstreams": {
            "mimo": {"base_url": MIMO_BASE_URL, "configured": bool(MIMO_API_KEY)},
            "claude": {"base_url": CLAUDE_BASE_URL, "configured": bool(CLAUDE_API_KEY)},
            "kimi": {"base_url": KIMI_BASE_URL, "configured": bool(KIMI_API_KEY)},
            "modelscope": {"base_url": MODELSCOPE_BASE_URL, "configured": bool(MODELSCOPE_API_TOKEN)},
            "glm": {"base_url": GLM_BASE_URL, "configured": bool(GLM_API_KEY)},
        },
    }


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def proxy(request: Request, path: str):
    body = await request.body()
    incoming_headers = {k.lower(): v for k, v in request.headers.items()}
    log_request(request.method, path, dict(request.headers), body)

    # 对 /v1/models 请求返回本地聚合的模型列表
    clean_path = path.lstrip("/")
    if clean_path == "v1/models":
        return Response(
            content=json.dumps({"object": "list", "data": SUPPORTED_MODELS}),
            media_type="application/json",
        )

    # 决定上游
    try:
        upstream_name, base_url, api_key, path_prefix, needs_conversion = resolve_upstream(body, path)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # base_url 去尾斜杠
    base = base_url.rstrip("/")

    # 判断流式请求
    is_stream = False
    original_body = body
    if body:
        try:
            data = json.loads(body)
            is_stream = data.get("stream", False)
        except Exception:
            pass

    # ==================== 协议转换分支 ====================
    if needs_conversion:
        # Anthropic → OpenAI 请求转换
        try:
            anthropic_body = json.loads(body)
            model_id = anthropic_body.get("model", "deepseek-ai/DeepSeek-V3.2")
            # 当路由到魔搭但 model_id 不是 deepseek 时，兜底映射到 DeepSeek-V3.2
            if upstream_name == "modelscope" and "deepseek" not in model_id.lower():
                model_id = "deepseek-ai/DeepSeek-V3.2"
            openai_body = anthropic_to_openai_request(anthropic_body, model_id)
            body = json.dumps(openai_body, ensure_ascii=False).encode("utf-8")
            # 终端路由日志（协议转换分支）
            if upstream_name == "modelscope":
                ts = time.strftime("%H:%M:%S")
                original_model = anthropic_body.get("model", "")
                print(f"\n{'='*50}", flush=True)
                print(f"[{ts}] 🔀 {original_model} → ModelScope / {model_id}", flush=True)
                print(f"{'='*50}", flush=True)
            if base.endswith("/v1") or upstream_name == "glm":
                target_url = f"{base}/chat/completions"
            else:
                target_url = f"{base}/v1/chat/completions"
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"协议转换失败: {exc}")

        # 组装转发 headers
        incoming_headers.pop("host", None)
        incoming_headers.pop("authorization", None)
        incoming_headers.pop("api-key", None)
        incoming_headers.pop("x-api-key", None)
        incoming_headers.pop("x-apikey", None)
        incoming_headers.pop("content-length", None)
        incoming_headers.pop("accept-encoding", None)

        outgoing_headers = {
            **{k: v for k, v in incoming_headers.items()},
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        if is_stream:
            async def converted_stream_generator() -> AsyncGenerator[bytes, None]:
                async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as inner_client:
                    async with inner_client.stream(
                        method=request.method,
                        url=target_url,
                        headers=outgoing_headers,
                        content=body,
                    ) as resp:
                        if resp.status_code >= 400:
                            err_body = await resp.aread()
                            error_text = err_body.decode("utf-8", errors="replace")
                            log_request(
                                request.method, path, {}, b"",
                                status=resp.status_code,
                                error=error_text[:500],
                                upstream=upstream_name,
                            )
                            yield err_body
                            return

                        async for sse_chunk in openai_stream_to_anthropic_sse(resp.aiter_bytes(), model_id):
                            yield sse_chunk

            return StreamingResponse(
                converted_stream_generator(),
                media_type="text/event-stream",
            )

        # 非流式：转请求 → 发上游 → 转响应
        client = httpx.AsyncClient(timeout=120.0, follow_redirects=True)
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=outgoing_headers,
                content=body,
            )
            safe_headers = {}
            for k, v in resp.headers.items():
                if k.lower() in ("content-type", "x-request-id"):
                    safe_headers[k] = v

            log_request(request.method, path, {}, b"", status=resp.status_code, upstream=upstream_name)

            # OpenAI → Anthropic 响应转换
            try:
                openai_data = json.loads(resp.content)
                anthropic_data = openai_to_anthropic_response(openai_data, model_id)
                patched_content = json.dumps(anthropic_data, ensure_ascii=False).encode("utf-8")
            except Exception:
                # 转换失败时回退原响应（方便调试）
                patched_content = resp.content

            return Response(
                content=patched_content,
                status_code=resp.status_code,
                headers=safe_headers,
            )
        except httpx.RequestError as exc:
            log_request(request.method, path, {}, b"", status=502, error=str(exc), upstream=upstream_name)
            raise HTTPException(status_code=502, detail=f"代理转发失败 [{upstream_name}]: {exc}")
        finally:
            await client.aclose()

    # ==================== 原生 Anthropic 转发分支（MiMo / Claude） ====================

    # 自动去重 base_url 和 path 中的 /v1（如 base 以 /v1 结尾时）
    if base.endswith("/v1") and clean_path.startswith("v1/"):
        clean_path = clean_path[3:].lstrip("/")

    # 构建目标 URL
    effective_path = clean_path
    if effective_path.startswith("anthropic/"):
        effective_path = effective_path[10:]  # 去掉 "anthropic/" 前缀

    if effective_path == "v1/messages":
        if path_prefix:
            target_url = f"{base}/{path_prefix}/v1/messages"
        else:
            target_url = f"{base}/v1/messages"
    else:
        target_url = f"{base}/{effective_path}"

    # 通用模型名映射（修复上游不支持的模型名）
    MODEL_NAME_MAP = {
        # 魔搭 DeepSeek：R1 旧名映射到支持的 R1-0528
        "deepseek-ai/DeepSeek-R1": "deepseek-ai/DeepSeek-R1-0528",
    }
    try:
        data = json.loads(original_body)
        model_name = data.get("model", "")
        if model_name in MODEL_NAME_MAP:
            data["model"] = MODEL_NAME_MAP[model_name]
            original_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            if body is not original_body:
                body = original_body
    except Exception:
        pass

    # MiMo 上游：把 Claude 简写模型名映射为 MiMo 模型名，并删除 thinking 参数避免 reasoning_content 传回问题
    if upstream_name == "mimo":
        try:
            data = json.loads(original_body)
            model_name = data.get("model", "")
            # 记录原始模型名，用于终端日志
            original_model = model_name
            CLAUDE_TO_MIMO = {
                # 简写
                "haiku": "mimo-v2.5",
                "sonnet": "mimo-v2.5-pro",
                "opus": "mimo-v2-omni",
                "sonnet[1m]": "mimo-v2-tts",
                "opus[1m]": "mimo-v2.5-tts",
                # 完整名（Claude Code 内置默认模型名）
                "claude-haiku-4-5": "mimo-v2.5",
                "claude-haiku-4-5-20250929": "mimo-v2.5",
                "claude-sonnet-4-5": "mimo-v2.5-pro",
                "claude-sonnet-4-5-20250929": "mimo-v2.5-pro",
                "claude-sonnet-4-6": "mimo-v2.5-pro",
                "claude-sonnet-4-6-20250929": "mimo-v2.5-pro",
                "claude-opus-4-5": "mimo-v2-omni",
                "claude-opus-4-5-20250929": "mimo-v2-omni",
                "claude-opus-4-6": "mimo-v2-omni",
                "claude-opus-4-6-20250929": "mimo-v2-omni",
                # MiMo 多模态 / TTS（Claude Code 可直接指定）
                "mimo-v2-omni": "mimo-v2-omni",
                "mimo-v2-tts": "mimo-v2-tts",
                "mimo-v2.5-tts": "mimo-v2.5-tts",
                "mimo-v2.5-tts-voicedesign": "mimo-v2.5-tts-voicedesign",
            }
            if model_name in CLAUDE_TO_MIMO:
                data["model"] = CLAUDE_TO_MIMO[model_name]
            # 删除 thinking 参数：MiMo 的 thinking 模式要求传回 reasoning_content，
            # 但代理/Claude Code 无法保证正确传回，直接禁用避免 400
            if "thinking" in data:
                del data["thinking"]
            mapped_model = data.get("model", "")
            original_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            if body is not original_body:
                body = original_body
            # 终端路由日志：醒目展示模型映射
            ts = time.strftime("%H:%M:%S")
            if original_model != mapped_model:
                route_info = f"[{ts}] 🔀 {original_model} → MiMo / {mapped_model}"
            else:
                route_info = f"[{ts}] ✅ MiMo / {mapped_model}"
            print(f"\n{'='*50}", flush=True)
            print(route_info, flush=True)
            print(f"{'='*50}", flush=True)
            # 调试：确认删除后请求中是否还有 thinking
            debug_data = json.loads(original_body)
            has_thinking = "thinking" in debug_data
            status = "✅ 已删除" if not has_thinking else "⚠️ 仍在"
            print(f"[{ts}] thinking 参数: {status}", flush=True)
        except Exception as exc:
            # 调试：记录异常，避免静默吞掉错误
            import traceback
            err_msg = f"[MiMo_PATCH_ERROR] {exc}\n{traceback.format_exc()}"
            print(err_msg, flush=True)
            try:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {err_msg}\n")
            except Exception:
                pass

    # 读取原始 headers，去掉冲突字段（尤其是所有认证相关 headers）
    incoming_headers.pop("host", None)
    incoming_headers.pop("authorization", None)
    incoming_headers.pop("api-key", None)
    incoming_headers.pop("x-api-key", None)
    incoming_headers.pop("x-apikey", None)
    incoming_headers.pop("content-length", None)
    incoming_headers.pop("accept-encoding", None)

    # 组装转发 headers：注入对应上游的真实 Key
    outgoing_headers = {
        **{k: v for k, v in incoming_headers.items()},
        "Authorization": f"Bearer {api_key}",
        "api-key": api_key,
    }

    is_openai_path = "chat/completions" in path

    if is_stream:
        async def stream_generator(is_openai: bool = False) -> AsyncGenerator[bytes, None]:
            async with httpx.AsyncClient(
                timeout=120.0, follow_redirects=True
            ) as inner_client:
                async with inner_client.stream(
                    method=request.method,
                    url=target_url,
                    headers=outgoing_headers,
                    content=original_body,
                ) as resp:
                    if resp.status_code >= 400:
                        err_body = await resp.aread()
                        error_text = err_body.decode("utf-8", errors="replace")
                        log_request(
                            request.method,
                            path,
                            {},
                            b"",
                            status=resp.status_code,
                            error=error_text[:500],
                            upstream=upstream_name,
                        )
                        yield err_body
                        return
                    # 流式响应：逐行修补 SSE data 事件
                    buffer = b""
                    debug_sse_count = 0
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            buffer += chunk
                            # 按换行符分割，保留未完整的最后一行在 buffer 中
                            while True:
                                newline_pos = buffer.find(b"\n")
                                if newline_pos == -1:
                                    break
                                line = buffer[:newline_pos + 1]
                                buffer = buffer[newline_pos + 1:]
                                # 调试：打印 MiMo 原始 SSE 事件（前 5 条）
                                if not is_openai and line.startswith(b"data: {") and debug_sse_count < 5:
                                    debug_sse_count += 1
                                    try:
                                        evt = json.loads(line[6:].decode("utf-8"))
                                        evt_type = evt.get("type", "")
                                        if evt_type in ("content_block_start", "content_block_delta"):
                                            print(f"[MiMo_RAW] {json.dumps(evt, ensure_ascii=False)[:400]}", flush=True)
                                    except Exception:
                                        pass
                                if is_openai:
                                    patched_line = patch_openai_sse_line(line)
                                else:
                                    patched_line = patch_anthropic_sse_line(line)
                                yield patched_line
                    # 输出 buffer 中剩余的内容
                    if buffer:
                        if is_openai:
                            patched_line = patch_openai_sse_line(buffer)
                        else:
                            patched_line = patch_anthropic_sse_line(buffer)
                        yield patched_line

        return StreamingResponse(
            stream_generator(is_openai=is_openai_path),
            media_type="text/event-stream",
        )

    # 非流式代理
    client = httpx.AsyncClient(timeout=120.0, follow_redirects=True)
    try:
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=outgoing_headers,
            content=original_body,
        )
        safe_headers = {}
        for k, v in resp.headers.items():
            if k.lower() in ("content-type", "x-request-id"):
                safe_headers[k] = v
        # 记录响应日志（401时额外记录 outgoing_headers）
        if resp.status_code == 401:
            debug_info = f"OUTGOING_HEADERS={json.dumps(dict(outgoing_headers), ensure_ascii=False)}"
            log_request(
                request.method, path, {}, b"", status=resp.status_code,
                error=debug_info[:800], upstream=upstream_name
            )
        else:
            log_request(
                request.method, path, {}, b"", status=resp.status_code, upstream=upstream_name
            )
        # 非流式响应：根据格式选择修补函数
        if is_openai_path:
            patched_content = patch_openai_json(resp.content)
        else:
            patched_content = patch_anthropic_json(resp.content)
        return Response(
            content=patched_content,
            status_code=resp.status_code,
            headers=safe_headers,
        )
    except httpx.RequestError as exc:
        log_request(
            request.method, path, {}, b"", status=502, error=str(exc), upstream=upstream_name
        )
        raise HTTPException(
            status_code=502, detail=f"代理转发失败 [{upstream_name}]: {exc}"
        )
    finally:
        await client.aclose()


if __name__ == "__main__":
    import uvicorn

    print("[Multi-Model Proxy] 启动中...")
    print(f"  监听地址: http://{PROXY_HOST}:{PROXY_PORT}")
    print(f"  MiMo 上游: {MIMO_BASE_URL}")
    print(f"  Claude 上游: {CLAUDE_BASE_URL}")
    print(f"  Kimi 上游: {KIMI_BASE_URL} (协议转换)")
    print(f"  魔搭上游: {MODELSCOPE_BASE_URL} (DeepSeek 协议转换)")
    print(f"  GLM 上游: {GLM_BASE_URL} (协议转换)")
    print(f"  健康检查: http://{PROXY_HOST}:{PROXY_PORT}/health")
    print("  按 Ctrl+C 停止\n")
    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT, log_level="warning")
