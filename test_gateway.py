"""直接测试网关对 Claude 的响应"""
import httpx
import json

with httpx.Client(timeout=60) as client:
    # 测试流式响应
    body = {
        "model": "claude-sonnet-4-5-20250929",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1024,
        "stream": True
    }

    print("=== 测试流式 Claude 请求 ===")
    resp = client.post(
        "http://127.0.0.1:8787/anthropic/v1/messages",
        headers={"Authorization": "Bearer local-proxy", "Content-Type": "application/json"},
        json=body
    )
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('content-type')}")
    print(f"Response length: {len(resp.text)}")
    print("\n原始响应前 3000 字符:")
    print(resp.text[:3000])

    print("\n\n=== 测试非流式 Claude 请求 ===")
    body["stream"] = False
    resp2 = client.post(
        "http://127.0.0.1:8787/anthropic/v1/messages",
        headers={"Authorization": "Bearer local-proxy", "Content-Type": "application/json"},
        json=body
    )
    print(f"Status: {resp2.status_code}")
    print(f"Response body:")
    try:
        data2 = resp2.json()
        print(json.dumps(data2, indent=2, ensure_ascii=False)[:2000])
    except Exception as e:
        print(f"Parse error: {e}")
        print(resp2.text[:2000])
