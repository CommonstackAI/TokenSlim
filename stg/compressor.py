"""渐进式 LLM 对话历史压缩器"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import config
from .token_counter import TokenCounter


@dataclass
class CompressionResult:
    """压缩结果"""
    compressed_messages: list[dict[str, Any]]
    was_compressed: bool = False
    original_tokens: int = 0
    compressed_tokens: int = 0
    compression_ratio: float = 1.0
    compressor_tokens_used: int = 0
    summary_regenerated: bool = False
    summary_compressed: bool = False
    stored_messages: list[dict[str, Any]] = field(default_factory=list)


SUMMARY_MARKER = "[对话摘要]"

COMPRESS_SYSTEM_PROMPT = """你是一个对话历史压缩助手。你的任务是将多轮对话压缩成简洁的摘要。

规则：
1. 保留所有关键事实、决策、代码片段、技术细节和数据点
2. 删除问候语、重复内容、填充词和确认信息
3. 使用与原始对话相同的语言输出
4. 为每个主要讨论主题包含 [idx:MSG_ID] 引用标签
5. 简洁输出，仅使用必要的 token
6. 输出以 [对话摘要] 开头"""


class PromptCompressor:
    """提示压缩器"""

    def __init__(self):
        self.token_counter = TokenCounter()
        self.client = httpx.AsyncClient(timeout=300.0)

    def _generate_idx(self) -> str:
        """生成 idx 标记"""
        return f"msg_{uuid.uuid4().hex[:8]}"

    def _count_recent_rounds(self, messages: list[dict[str, Any]]) -> int:
        """从末尾往前计算最近 N 轮对话包含多少条消息"""
        keep_rounds = config.compressor_keep_recent_rounds
        count = 0
        rounds = 0

        # 从末尾往前扫描
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            role = msg.get("role")

            # 跳过 system 消息
            if role == "system":
                continue

            count += 1

            # 每遇到一个 user 消息，算作一轮的开始
            if role == "user":
                rounds += 1
                if rounds >= keep_rounds:
                    break

        return count

    def _extract_existing_summary(self, messages: list[dict[str, Any]]) -> tuple[str | None, int]:
        """提取现有的摘要内容

        Returns:
            (summary_content, summary_index) 如果找到摘要
            (None, -1) 如果没有找到
        """
        for i, msg in enumerate(messages):
            if msg.get("role") == "assistant" and SUMMARY_MARKER in msg.get("content", ""):
                return msg["content"], i
        return None, -1

    def _split_messages(self, messages: list[dict[str, Any]]) -> tuple[
        list[dict[str, Any]],  # system messages
        list[dict[str, Any]],  # old messages (to compress)
        list[dict[str, Any]],  # recent messages (to keep)
        str | None,            # existing summary content
        int,                   # summary index in original messages
    ]:
        """将 messages 分割为 system / old / recent 三部分"""
        system_msgs = []
        non_system_msgs = []
        existing_summary = None
        summary_idx = -1

        for i, msg in enumerate(messages):
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                system_msgs.append(msg)
            elif role == "assistant" and SUMMARY_MARKER in content:
                existing_summary = content
                summary_idx = i
            else:
                non_system_msgs.append(msg)

        # 从末尾往前保留最近 N 轮
        recent_count = self._count_recent_rounds(non_system_msgs)
        if recent_count >= len(non_system_msgs):
            # 所有消息都在最近 N 轮内，无需压缩
            return system_msgs, [], non_system_msgs, existing_summary, summary_idx

        old_msgs = non_system_msgs[:-recent_count] if recent_count > 0 else non_system_msgs
        recent_msgs = non_system_msgs[-recent_count:] if recent_count > 0 else []

        return system_msgs, old_msgs, recent_msgs, existing_summary, summary_idx

    async def _call_compressor_llm(
        self,
        content_to_compress: str,
        max_tokens: int,
        existing_summary: str | None = None,
    ) -> tuple[str, int]:
        """调用压缩 LLM 生成摘要

        Returns:
            (summary_text, tokens_used)
        """
        user_prompt = f"请将以下对话历史压缩为摘要，不超过 {max_tokens} tokens:\n\n{content_to_compress}"
        if existing_summary:
            user_prompt += f"\n\n已有的对话摘要（需要合并）:\n{existing_summary}"

        payload = {
            "model": config.compressor_model,
            "messages": [
                {"role": "system", "content": COMPRESS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.upstream_api_key}",
        }

        print(f"[STG Compressor] Calling {config.compressor_model} for compression...")
        response = await self.client.post(
            f"{config.upstream_base_url}/chat/completions",
            json=payload,
            headers=headers,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Compressor LLM returned {response.status_code}: {response.text}"
            )

        data = response.json()
        summary = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_used = usage.get("total_tokens", 0)

        # 确保摘要以 [对话摘要] 开头
        if not summary.startswith(SUMMARY_MARKER):
            summary = f"{SUMMARY_MARKER} {summary}"

        print(f"[STG Compressor] Summary generated: {len(summary)} chars, {tokens_used} tokens used")
        return summary, tokens_used

    def _format_messages_for_compression(self, messages: list[dict[str, Any]]) -> str:
        """将消息列表格式化为压缩 LLM 的输入文本"""
        lines = []
        for msg in messages:
            idx = self._generate_idx()
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"[{role}] [idx:{idx}] {content}")
        return "\n\n".join(lines)

    async def compress(self, messages: list[dict[str, Any]]) -> CompressionResult:
        """压缩对话历史

        渐进式压缩策略：
        1. 如果 total_tokens < threshold，不压缩
        2. 首次压缩：保留最近 N 轮，压缩其余部分
        3. 后续压缩：合并新摘要到旧摘要
        4. 如果摘要超过阈值，进行二次压缩
        """
        # 计算原始 token 数
        original_tokens = self.token_counter.count_messages_tokens(messages)
        threshold = config.compressor_threshold_tokens

        print(f"[STG Compressor] Original tokens: {original_tokens}, threshold: {threshold}")

        # 如果未超过阈值，不压缩
        if original_tokens < threshold:
            print(f"[STG Compressor] Below threshold, no compression needed")
            return CompressionResult(
                compressed_messages=messages,
                was_compressed=False,
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
            )

        # 分割消息
        system_msgs, old_msgs, recent_msgs, existing_summary, summary_idx = self._split_messages(messages)

        # 如果没有旧消息需要压缩，直接返回
        if not old_msgs:
            print(f"[STG Compressor] No old messages to compress")
            return CompressionResult(
                compressed_messages=messages,
                was_compressed=False,
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
            )

        print(f"[STG Compressor] Compressing {len(old_msgs)} old messages, keeping {len(recent_msgs)} recent")

        # 格式化待压缩内容
        content_to_compress = self._format_messages_for_compression(old_msgs)

        # 计算摘要目标长度
        old_tokens = self.token_counter.count_messages_tokens(old_msgs)
        target_summary_tokens = int(old_tokens * 0.3)
        max_summary_tokens = config.compressor_summary_max_tokens

        # 调用压缩 LLM
        summary, compressor_tokens = await self._call_compressor_llm(
            content_to_compress,
            max_tokens=min(target_summary_tokens, max_summary_tokens),
            existing_summary=existing_summary,
        )

        # 检查合并后的摘要是否超过阈值
        summary_tokens = self.token_counter.count_tokens(summary)
        summary_regenerated = existing_summary is not None
        summary_compressed = False

        if summary_tokens > threshold:
            print(f"[STG Compressor] Summary too long ({summary_tokens} tokens), performing secondary compression")
            # 二次压缩：对摘要本身进行压缩
            secondary_summary, secondary_tokens = await self._call_compressor_llm(
                summary,
                max_tokens=max_summary_tokens,
                existing_summary=None,
            )
            summary = secondary_summary
            compressor_tokens += secondary_tokens
            summary_compressed = True

        # 构建压缩后的 messages
        compressed_messages = []

        # 添加 system messages
        compressed_messages.extend(system_msgs)

        # 添加摘要（作为 assistant 消息）
        compressed_messages.append({
            "role": "assistant",
            "content": summary,
        })

        # 添加最近的消息
        compressed_messages.extend(recent_msgs)

        # 计算压缩后的 token 数
        compressed_tokens = self.token_counter.count_messages_tokens(compressed_messages)
        compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 1.0

        print(f"[STG Compressor] Compression complete:")
        print(f"  Original: {original_tokens} tokens")
        print(f"  Compressed: {compressed_tokens} tokens")
        print(f"  Ratio: {compression_ratio:.2%}")
        print(f"  Compressor used: {compressor_tokens} tokens")
        print(f"  Summary regenerated: {summary_regenerated}")
        print(f"  Summary compressed: {summary_compressed}")

        return CompressionResult(
            compressed_messages=compressed_messages,
            was_compressed=True,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compression_ratio,
            compressor_tokens_used=compressor_tokens,
            summary_regenerated=summary_regenerated,
            summary_compressed=summary_compressed,
            stored_messages=old_msgs,  # 这些消息需要存入 History Index
        )
