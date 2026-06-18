#!/usr/bin/env python3
"""端到端冒烟：解析原题 → 按条件改编 → 不超纲校验。

需要先配置 provider 与对应 API key（见 .env.example）。脚本会用当前
LLM_PROVIDER（anthropic 或 openai）跑完整条流水线，并打印每道新题的
答案、知识点、改编理由与不超纲校验结果。

用法：
  python scripts/smoke.py                          # 用内置示例文本题
  python scripts/smoke.py --text "计算 3/4 + 1/6"   # 自定义文本题
  python scripts/smoke.py --file 题目.png           # 用图片/PDF（PDF 仅 anthropic 模式）
  python scripts/smoke.py --difficulty harder --scenario 购物 --count 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 让脚本能直接 import app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.claude_service import (  # noqa: E402
    ConfigError,
    RefusalError,
    adapt_problem,
    parse_problem,
    verify_in_scope,
)
from app.config import get_settings  # noqa: E402
from app.content import build_problem_parts  # noqa: E402
from app.schemas import AdaptConditions  # noqa: E402

SAMPLE = "小明从家到学校骑自行车用了 15 分钟，速度是每分钟 200 米。求小明家到学校的距离。"


def line(char: str = "-", n: int = 60) -> str:
    return char * n


def main() -> int:
    ap = argparse.ArgumentParser(description="题目改编端到端冒烟测试")
    ap.add_argument("--text", default=SAMPLE, help="文本题目（默认用内置示例）")
    ap.add_argument("--file", help="图片/PDF/文本文件路径（优先于 --text）")
    ap.add_argument("--count", type=int, default=2, help="生成新题数量 1-5")
    ap.add_argument(
        "--difficulty", choices=["easier", "keep", "harder"], default="harder", help="难度调整"
    )
    ap.add_argument("--scenario", default="购物", help="情境主题，可空")
    ap.add_argument(
        "--change-mode",
        choices=["values", "scenario", "phrasing", "comprehensive"],
        default="comprehensive",
    )
    args = ap.parse_args()

    s = get_settings()
    print(line("="))
    print(f"provider = {s.provider}   model = {s.model}   has_api_key = {s.has_api_key}")
    print(line("="))
    if not s.has_api_key:
        print("\n[未配置 API key] 请先设置环境变量，例如：")
        print("  # Anthropic 官方")
        print("  export LLM_PROVIDER=anthropic")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        print("  # 或 OpenAI 兼容代理（codexzh 等）")
        print("  export LLM_PROVIDER=openai")
        print("  export OPENAI_API_KEY=...")
        print("  export OPENAI_BASE_URL=https://api.codexzh.com/v1")
        print("  export OPENAI_MODEL=claude-opus-4-8   # 或 gpt-5.5 等")
        return 1

    file_name = file_bytes = None
    if args.file:
        p = Path(args.file)
        if not p.exists():
            print(f"[错误] 文件不存在: {p}")
            return 1
        file_name, file_bytes = p.name, p.read_bytes()
        pasted = None
    else:
        pasted = args.text

    try:
        parts = build_problem_parts(file_name, file_bytes, pasted)

        print("\n【1/3】解析原题 …")
        parsed = parse_problem(parts)
        print("  题干    :", parsed.problem_text)
        print("  知识点  :", "、".join(parsed.knowledge_points))
        print("  学段    :", parsed.grade_band)
        print("  难度/题型:", parsed.difficulty, "/", parsed.problem_type)

        conditions = AdaptConditions(
            difficulty_change=args.difficulty,
            scenario_theme=args.scenario,
            change_mode=args.change_mode,
            count=args.count,
        )
        print(f"\n【2/3】改编（难度={args.difficulty} 情境={args.scenario or '—'} 数量={args.count}）…")
        result = adapt_problem(parsed, conditions)

        print("\n【3/3】不超纲独立校验 …")
        checks = verify_in_scope(parsed, result)
        check_by_index = {c.index: c for c in checks.checks}

        print("\n" + line("="))
        print("改编结果")
        print(line("="))
        passed_count = 0
        for i, v in enumerate(result.variants):
            chk = check_by_index.get(i)
            ok = chk.passed if chk else True
            passed_count += 1 if ok else 0
            badge = "✓ 不超纲" if ok else "✗ 可能超纲"
            print(f"\n[新题 {i + 1}] {badge}")
            print("  题干    :", v.stem)
            print("  参考答案:", v.answer)
            print("  解析    :", v.solution)
            print("  知识点  :", "、".join(v.knowledge_points), "| 难度:", v.difficulty)
            print("  改编理由:", v.adaptation_reason)
            print("  不超纲自检:", v.within_scope_note)
            if chk:
                print("  校验说明:", chk.reason)

        print("\n" + line("="))
        print(f"完成：共 {len(result.variants)} 道，不超纲 {passed_count} 道。")
        return 0

    except ConfigError as exc:
        print(f"\n[配置错误] {exc}")
        return 1
    except RefusalError as exc:
        print(f"\n[模型拒绝] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\n[失败] {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
