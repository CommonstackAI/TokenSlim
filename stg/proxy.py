"""ASGI 代理主入口"""

import json
import time
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from .config import Config
from .token_counter import TokenCounter
from .compressor import PromptCompressor


class STGProxy:
    """Smart Token Gateway 代理"""

    def __init__(self, config: Config):
        self.config = config
        self.token_counter = TokenCounter()
        self.compressor = PromptCompressor()
        self.client = httpx.AsyncClient(timeout=300.0)

    async def handle_chat_completions(self, request: Request) -> Response:
        """处理 /v1/chat/completions 请求"""
        start_time = time.time()

        # 读取请求体
        body = await request.body()
        payload = json.loads(body.decode('utf-8'))

        print(f"\n[STG] ===== New Request =====")
        print(f"[STG] Model: {payload.get('model')}")
        print(f"[STG] Messages count: {len(payload.get('messages', []))}")

        # 计算原始 token 数
        messages = payload.get("messages", [])
        original_tokens = self.token_counter.count_messages_tokens(messages)
        print(f"[STG] Original tokens: {original_tokens}")

        # 压缩逻辑
        compression_result = await self.compressor.compress(messages)

        compressed_payload = payload.copy()
        compressed_payload["messages"] = compression_result.compressed_messages
        compressed_tokens = compression_result.compressed_tokens

        # 转发到上游
        print(f"[STG] Forwarding to upstream: {self.config.upstream_base_url}")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.upstream_api_key}",
        }

        # 检查是否是 streaming 请求
        is_stream = payload.get("stream", False)

        if is_stream:
            # Streaming 响应
            async def stream_response():
                async with self.client.stream(
                    "POST",
                    f"{self.config.upstream_base_url}/chat/completions",
                    json=compressed_payload,
                    headers=headers,
                ) as response:
                    async for chunk in response.aiter_bytes():
                        yield chunk

            return StreamingResponse(
                stream_response(),
                media_type="text/event-stream",
                headers={
                    "X-STG-Original-Tokens": str(original_tokens),
                    "X-STG-Compressed-Tokens": str(compressed_tokens),
                    "X-STG-Compressed": str(compression_result.was_compressed).lower(),
                    "X-STG-Compression-Ratio": f"{compression_result.compression_ratio:.2f}",
                },
            )
        else:
            # 非 streaming 响应
            response = await self.client.post(
                f"{self.config.upstream_base_url}/chat/completions",
                json=compressed_payload,
                headers=headers,
            )

            elapsed_ms = (time.time() - start_time) * 1000

            # 解析响应
            response_data = response.json()
            usage = response_data.get("usage", {})

            print(f"[STG] Response received")
            print(f"[STG] Prompt tokens: {usage.get('prompt_tokens', 0)}")
            print(f"[STG] Completion tokens: {usage.get('completion_tokens', 0)}")
            print(f"[STG] Total tokens: {usage.get('total_tokens', 0)}")
            print(f"[STG] Elapsed: {elapsed_ms:.0f}ms")
            print(f"[STG] ===== End Request =====\n")

            # 过滤掉可能导致问题的响应头
            response_headers = dict(response.headers)
            # 移除 content-encoding 因为我们返回的是解码后的内容
            response_headers.pop("content-encoding", None)
            response_headers.pop("content-length", None)  # 长度会变化

            return Response(
                content=json.dumps(response_data),
                status_code=response.status_code,
                media_type="application/json",
                headers={
                    **response_headers,
                    "X-STG-Original-Tokens": str(original_tokens),
                    "X-STG-Compressed-Tokens": str(compressed_tokens),
                    "X-STG-Compressed": str(compression_result.was_compressed).lower(),
                    "X-STG-Compression-Ratio": f"{compression_result.compression_ratio:.2f}",
                    "X-STG-Compressor-Tokens": str(compression_result.compressor_tokens_used),
                    "X-STG-Summary-Regenerated": str(compression_result.summary_regenerated).lower(),
                    "X-STG-Summary-Compressed": str(compression_result.summary_compressed).lower(),
                    "X-STG-Gateway-Latency-Ms": str(int(elapsed_ms)),
                },
            )

    async def handle_other(self, request: Request) -> Response:
        """处理其他请求（透传）"""
        print(f"[STG] Passthrough: {request.method} {request.url.path}")

        # 读取请求体
        body = await request.body()

        # 构建上游 URL
        upstream_url = f"{self.config.upstream_base_url}{request.url.path}"
        if request.url.query:
            upstream_url += f"?{request.url.query}"

        # 转发请求
        headers = dict(request.headers)
        headers["Authorization"] = f"Bearer {self.config.upstream_api_key}"

        response = await self.client.request(
            method=request.method,
            url=upstream_url,
            content=body,
            headers=headers,
        )

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers),
        )


def create_app(config: Config) -> Starlette:
    """创建 Starlette 应用"""
    proxy = STGProxy(config)

    async def chat_completions(request: Request) -> Response:
        return await proxy.handle_chat_completions(request)

    async def other(request: Request) -> Response:
        return await proxy.handle_other(request)

    app = Starlette(
        debug=True,
        routes=[
            Route("/v1/chat/completions", chat_completions, methods=["POST"]),
            Route("/{path:path}", other, methods=["GET", "POST", "PUT", "DELETE", "PATCH"]),
        ],
    )

    return app


# 创建全局 app 实例
from .config import config
app = create_app(config)
