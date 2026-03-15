#!/bin/bash
# OpenClaw + STG 集成测试脚本

echo "=========================================="
echo "OpenClaw + STG 集成测试"
echo "=========================================="
echo ""

# 设置代理
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890

# 测试 1: 简单对话（不触发压缩）
echo "测试 1: 简单对话（应该不触发压缩）"
echo "------------------------------------------"
echo "请解释什么是 CAP 定理" | openclaw chat --model openrouter:auto --no-stream 2>&1 | tail -20
echo ""
echo ""

# 测试 2: 创建一个长对话来触发压缩
echo "测试 2: 长对话测试（应该触发压缩）"
echo "------------------------------------------"

# 创建临时会话文件
SESSION_FILE="/tmp/openclaw_stg_test_session.txt"
cat > "$SESSION_FILE" << 'EOF'
请详细解释分布式系统中的 CAP 定理，包括一致性、可用性和分区容错性的含义。
EOF

echo "第 1 轮: 询问 CAP 定理"
cat "$SESSION_FILE" | openclaw chat --model openrouter:auto --no-stream --session stg-test 2>&1 | tail -20
echo ""

# 第 2 轮
echo "第 2 轮: 询问实际案例"
echo "请举几个实际的分布式系统案例，说明它们如何在 CAP 中做出权衡选择。" | openclaw chat --model openrouter:auto --no-stream --session stg-test 2>&1 | tail -20
echo ""

# 第 3 轮
echo "第 3 轮: 询问 BASE 理论"
echo "那么 BASE 理论和 CAP 定理有什么关系？请详细说明。" | openclaw chat --model openrouter:auto --no-stream --session stg-test 2>&1 | tail -20
echo ""

# 第 4 轮 - 这一轮应该触发压缩
echo "第 4 轮: 总结（应该触发压缩）"
echo "请总结一下我们讨论的所有内容，包括 CAP 定理、实际案例和 BASE 理论。" | openclaw chat --model openrouter:auto --no-stream --session stg-test 2>&1 | tail -20
echo ""

echo "=========================================="
echo "测试完成！"
echo "=========================================="
echo ""
echo "请检查 STG 服务器日志，查看压缩是否被触发。"
echo "预期：第 4 轮对话应该触发压缩（总 tokens > 4096）"
