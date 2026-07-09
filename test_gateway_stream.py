"""测试本地网关的流式响应完整性"""
import httpx
import json
import time

body = {
    "model": "claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "hi"}],
    "max_tokens": 1024,
    "stream": True,
}

print("=== 通过网关发送流式请求 ===")
start = time.time()
with httpx.Client(timeout=60) as client:
    with client.stream(
        "POST",
        "http://127.0.0.1:8787/anthropic/v1/messages",
        headers={"Authorization": "Bearer local-proxy", "Content-Type": "application/json"},
        json=body
    ) as resp:
        print(f"Status: {resp.status_code} (after {time.time()-start:.2f}s)")
        print(f"Content-Type: {resp.headers.get('content-type')}")
        
        events = []
        text = ""
        for chunk in resp.iter_text():
            text += chunk
            # 实时打印每个 chunk
            print(f"[chunk {len(chunk)} chars, total {len(text)}]")
            if len(text) > 5000:
                break  # 避免太多输出
        
        print(f"\n完整响应（前4000字符）:")
        print(text[:4000])
        
        print(f"\n解析事件:")
        for line in text.strip().split('\n'):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    events.append(data.get("type", "unknown"))
                except:
                    events.append("parse_error")
        print(f"事件序列: {events}")
        print(f"总耗时: {time.time()-start:.2f}s")
