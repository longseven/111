"""运行配置，从环境变量读取。

支持两种 provider：
- anthropic：Anthropic 官方 API（默认，支持图片 + PDF）
- openai：任意 OpenAI 兼容代理（如 codexzh），通过 base_url 指向；支持图片 + 文本
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from functools import lru_cache
from pathlib import Path

# 可在页面「设置」里在线覆盖的配置项（运行时覆盖文件优先于环境变量）
RUNTIME_KEYS = (
    "LLM_PROVIDER",
    "ANTHROPIC_API_KEY",
    "ADAPT_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
)


def _runtime_path() -> Path:
    override = os.environ.get("CONFIG_PATH", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "data" / "runtime.json"


def _load_runtime() -> dict:
    """读取在线设置写入的运行时覆盖（JSON），损坏/缺失时返回空。"""
    path = _runtime_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def update_runtime(updates: dict) -> None:
    """合并并落盘运行时覆盖；仅接受白名单键，空字符串表示「清除该项、回退环境变量」。"""
    path = _runtime_path()
    current = _load_runtime()
    for key, value in updates.items():
        if key not in RUNTIME_KEYS:
            continue
        text = "" if value is None else str(value)
        if text.strip() == "":
            current.pop(key, None)
        else:
            current[key] = text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    get_settings.cache_clear()


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
        rt = _load_runtime()

        def val(key: str, default: str = "") -> str:
            # 在线设置（运行时覆盖）优先，其次环境变量/.env，最后默认值
            if key in rt and str(rt[key]).strip() != "":
                return str(rt[key])
            return os.environ.get(key, default)

        # 选择 provider：anthropic（默认）/ openai
        self.provider: str = val("LLM_PROVIDER", "anthropic").strip().lower()

        # Anthropic 官方
        self.anthropic_api_key: str = val("ANTHROPIC_API_KEY", "")
        self.anthropic_model: str = val("ADAPT_MODEL", "claude-opus-4-8")

        # OpenAI 兼容代理
        self.openai_api_key: str = val("OPENAI_API_KEY", "")
        self.openai_base_url: str = val("OPENAI_BASE_URL", "").strip()
        self.openai_model: str = val("OPENAI_MODEL", "claude-opus-4-8")

        # 通用
        self.max_tokens: int = int(os.environ.get("MAX_TOKENS", "16000"))
        self.max_upload_bytes: int = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
        self.request_timeout: float = float(os.environ.get("REQUEST_TIMEOUT", "300"))

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


# ---------- 可选访问口令（轻量多用户/团队内网访问控制） ----------
AUTH_COOKIE = "k12_auth"


def auth_password() -> str:
    return os.environ.get("APP_PASSWORD", "").strip()


def auth_enabled() -> bool:
    return bool(auth_password())


def make_auth_token(password: str) -> str:
    """由口令派生不可逆登录令牌，写进 Cookie；改口令即令旧 Cookie 失效。"""
    secret = os.environ.get("APP_SECRET", "k12-adapt-secret")
    return hmac.new(secret.encode("utf-8"), password.encode("utf-8"), hashlib.sha256).hexdigest()


def valid_token(token: str | None) -> bool:
    if not auth_enabled():
        return True
    if not token:
        return False
    return hmac.compare_digest(token, make_auth_token(auth_password()))
