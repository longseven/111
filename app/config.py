"""运行配置，从环境变量读取。

支持两种 provider：
- anthropic：Anthropic 官方 API（默认，支持图片 + PDF）
- openai：任意 OpenAI 兼容代理（如 codexzh），通过 base_url 指向；支持图片 + 文本
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _load_dotenv(env_path: Path | None = None) -> None:
    """若项目根目录存在 .env，则把其中键值加载到 os.environ（不覆盖已有变量）。

    .env 格式：每行 KEY=value，# 开头为注释，值两侧的引号会被去掉。
    已存在的真实环境变量优先于 .env。
    """
    env_path = env_path or (Path(__file__).resolve().parent.parent / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# 模块导入时自动加载 .env，便于本地一键运行
_load_dotenv()


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
