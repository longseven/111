"""运行配置，从环境变量读取。"""
from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
        self.model: str = os.environ.get("ADAPT_MODEL", "claude-opus-4-8")
        self.max_tokens: int = int(os.environ.get("MAX_TOKENS", "16000"))
        self.max_upload_bytes: int = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
