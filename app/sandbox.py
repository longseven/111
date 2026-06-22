"""沙箱执行模型生成的 sympy 验算代码。

安全措施：独立子进程（python -I）、超时、受限 __builtins__、import 仅放行
sympy/math/fractions/decimal。威胁模型是「模型生成的数学代码」而非攻击者，
但仍尽量收紧，避免死循环/越权。代码需自行设置 result(bool) 与 computed(str)。
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict

_RUNNER = r'''
import json, sys
import builtins as _b

_real_import = _b.__import__
_ALLOWED_MODULES = {"sympy", "math", "fractions", "decimal", "cmath"}


def _safe_import(name, *a, **k):
    if name.split(".")[0] in _ALLOWED_MODULES:
        return _real_import(name, *a, **k)
    raise ImportError("仅允许 import sympy/math 等数学库")


_ALLOWED = {
    "abs", "min", "max", "range", "len", "sum", "pow", "round", "int", "float",
    "str", "bool", "list", "tuple", "dict", "set", "frozenset", "enumerate",
    "zip", "map", "filter", "sorted", "reversed", "all", "any", "divmod",
    "True", "False", "None", "print", "isinstance", "ValueError", "Exception",
}
_safe = {k: getattr(_b, k) for k in _ALLOWED if hasattr(_b, k)}
_safe["__import__"] = _safe_import

import sympy
ns = {"__builtins__": _safe, "sympy": sympy, "sp": sympy}

code = sys.stdin.read()
out = {}
try:
    exec(code, ns)
    if "result" in ns and ns["result"] is not None:
        out["result"] = bool(ns["result"])
    else:
        out["result"] = None
    out["computed"] = str(ns.get("computed", ""))[:300]
except Exception as e:
    out["error"] = "{}: {}".format(type(e).__name__, e)
print(json.dumps(out))
'''


def run_check(code: str, timeout: float = 6.0) -> Dict[str, Any]:
    """执行验算代码，返回 {ran, result, computed, error}。

    result：True=给定答案与独立计算一致，False=不一致，None=代码未判定/不可判定。
    """
    if not code or not code.strip():
        return {"ran": False, "result": None, "computed": "", "error": "无验算代码"}
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _RUNNER],
            input=code,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ran": False, "result": None, "computed": "", "error": "验算超时（可能死循环或计算过重）"}
    if proc.returncode != 0:
        return {"ran": False, "result": None, "computed": "", "error": (proc.stderr or "运行失败").strip()[:200]}
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return {"ran": False, "result": None, "computed": "", "error": "无法解析验算输出"}
    if "error" in data:
        return {"ran": True, "result": None, "computed": "", "error": str(data["error"])[:200]}
    return {"ran": True, "result": data.get("result"), "computed": data.get("computed", ""), "error": ""}
