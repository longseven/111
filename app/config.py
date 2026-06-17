"""运行配置，从环境变量读取。

支持两种 provider：
- anthropic：Anthropic 官方 API（默认，支持图片 + PDF）
- openai：任意 OpenAI 兼容代理（如 codexzh），通过 base_url 指向；支持图片 + 文本
"""
from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        # 选择 provider：anthropic（默认）/ openai
        self.provider: str = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()

        # Anthropic 官方
        self.anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
        self.anthropic_model: str = os.environ.get("ADAPT_MODEL", "claude-opus-4-8")

        # OpenAI 兼容代理
        self.openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
        self.openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "").strip()
        self.openai_model: str = os.environ.get("OPENAI_MODEL", "claude-opus-4-8")

        # 通用
        self.max_tokens: int = int(os.environ.get("MAX_TOKENS", "16000"))
        self.max_upload_bytes: int = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))

    @property
    def model(self) -> str:
        return self.openai_model if self.provider == "openai" else self.anthropic_model

    @property
    def has_api_key(self) -> bool:
        if self.provider == "openai":
            return bool(self.openai_api_key.strip())
        return bool(self.anthropic_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
