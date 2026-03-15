"""测试 STG 压缩功能"""

import json
import httpx

# 创建一个超过阈值的对话
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "解释 CAP 定理"},
    {"role": "assistant", "content": "CAP 定理是分布式系统中的一个重要理论。" * 500},  # 更长的回复
    {"role": "user", "content": "举个实际例子"},
    {"role": "assistant", "content": "比如 DynamoDB 选择了 AP，牺牲了强一致性。" * 500},  # 更长的回复
    {"role": "user", "content": "那和 BASE 有什么关系"},
    {"role": "assistant", "content": "BASE 理论是 CAP 的延伸，强调最终一致性。" * 500},  # 更长的回复
    {"role": "user", "content": "总结一下"},
]

payload = {
    "model": "qwen/qwen3.5-27b",
    "messages": messages,
    "max_tokens": 100,
    "temperature": 0.7,
    "stream": False,
}

print("发送测试请求到 STG...")
print(f"消息数量: {len(messages)}")

# 不使用代理，直接连接 STG
response = httpx.post(
    "http://127.0.0.1:8404/v1/chat/completions",
    json=payload,
    headers={"Content-Type": "application/json"},
    timeout=120.0,
)

print(f"\n状态码: {response.status_code}")
print(f"\n响应头:")
for key, value in response.headers.items():
    if key.lower().startswith("x-stg"):
        print(f"  {key}: {value}")

if response.status_code == 200:
    data = response.json()
    print(f"\n响应内容:")
    print(f"  Model: {data.get('model')}")
    print(f"  Choices: {len(data.get('choices', []))}")
    if data.get("choices"):
        content = data["choices"][0]["message"]["content"]
        print(f"  Content length: {len(content)} chars")
        print(f"  Content preview: {content[:200]}...")
else:
    print(f"\n错误: {response.text}")
