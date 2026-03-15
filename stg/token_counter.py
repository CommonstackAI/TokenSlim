"""Token 计数"""

import tiktoken


class TokenCounter:
    """Token 计数器"""

    def __init__(self, model: str = "gpt-4"):
        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            # 如果模型不支持，使用 cl100k_base（GPT-4 的编码）
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """计算文本的 token 数"""
        if not text:
            return 0
        return len(self.encoding.encode(text))

    def count_messages_tokens(self, messages: list[dict]) -> int:
        """
        计算 messages 数组的总 token 数

        参考 OpenAI 的计算方式
        """
        if not messages:
            return 0

        tokens = 0
        for message in messages:
            # 每条消息的固定开销：4 tokens
            tokens += 4

            # role
            tokens += self.count_tokens(message.get("role", ""))

            # content
            content = message.get("content", "")
            if content:
                tokens += self.count_tokens(content)

            # name (如果有)
            if "name" in message:
                tokens += self.count_tokens(message["name"])
                tokens += 1  # name 的额外开销

        # 整个 messages 的固定开销：2 tokens
        tokens += 2

        return tokens
