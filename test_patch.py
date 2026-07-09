from main import patch_anthropic_sse_line, patch_anthropic_json
import json

# 测试 message_delta（ Anthropic 标准格式：usage 在 delta 内部）
line = b'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}'
result = patch_anthropic_sse_line(line)
print('Test 1 - message_delta (no usage in delta):')
print('  Input:', line)
print('  Output:', result)
# 检查是否正确地在 delta 内部添加了 usage
data = json.loads(result[6:])  # 去掉 "data: "
print('  delta.usage:', data.get('delta', {}).get('usage'))
print()

# 测试 message_start（ Anthropic 标准格式：usage 在 message 内部）
line2 = b'data: {"type": "message_start", "message": {"id": "test", "role": "assistant"}}'
result2 = patch_anthropic_sse_line(line2)
print('Test 2 - message_start (no usage in message):')
print('  Input:', line2)
print('  Output:', result2)
data2 = json.loads(result2[6:])
print('  message.usage:', data2.get('message', {}).get('usage'))
print()

# 测试 message_stop
line3 = b'data: {"type": "message_stop"}'
result3 = patch_anthropic_sse_line(line3)
print('Test 3 - message_stop:')
print('  Input:', line3)
print('  Output:', result3)
print()

# 测试非流式响应（ usage 在顶层）
body = b'{"content": [], "id": "test"}'
result4 = patch_anthropic_json(body)
print('Test 4 - non-streaming (no usage):')
print('  Input:', body)
print('  Output:', result4)
