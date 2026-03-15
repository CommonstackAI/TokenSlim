"""配置加载"""

import json
from pathlib import Path
from typing import Any


class Config:
    """配置管理"""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self._data: dict[str, Any] = {}
        self.load()

    def load(self):
        """加载配置文件"""
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    @property
    def upstream_base_url(self) -> str:
        return self.get("upstream.base_url")

    @property
    def upstream_api_key(self) -> str:
        return self.get("upstream.api_key")

    @property
    def compressor_model(self) -> str:
        return self.get("compressor.model", "qwen/qwen3.5-27b")

    @property
    def compressor_threshold_tokens(self) -> int:
        return self.get("compressor.threshold_tokens", 4096)

    @property
    def compressor_keep_recent_rounds(self) -> int:
        return self.get("compressor.keep_recent_rounds", 2)

    @property
    def compressor_summary_max_tokens(self) -> int:
        return self.get("compressor.summary_max_tokens", 1228)

    @property
    def gateway_port(self) -> int:
        return self.get("gateway.port", 8404)

    @property
    def gateway_host(self) -> str:
        return self.get("gateway.host", "127.0.0.1")


# 全局配置实例
config = Config()
