#!/usr/bin/env python3
"""把本机真实失败的模型输出固化为回归 fixture。

用法：
    python capture_badcases.py            # 导出所有尚未固化的坏例
    python capture_badcases.py --all      # 重新导出（覆盖同名文件）

流程：
    1. 读取 backend/ai_calendar.db 中 status=failed 且带有效 diagnostic_json 的运行；
    2. 取出 raw_model_output（模型原始 JSON）；
    3. 脱敏后写入 backend/tests/fixtures/badcases/<阶段>_<错误类型>_<字段>.json；
    4. 提示去 tests/unit/test_badcase_regressions.py 补断言。

注意：成功运行的 diagnostic_json 会被 SQLAlchemy 存成字符串 "null"；
脚本在 SQL 层已排除 'null' 字符串，避免遍历无用记录。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "ai_calendar.db"
FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "badcases"

REPLACEMENTS = [
    ("zz处理流程", "A地办事流程"),
    ("前往zz", "前往A地"),
    ("zz", "A地"),
    ("开学注册", "现场登记"),
    ("宣讲会", "交流会"),
]


def sanitize(value: Any) -> Any:
    if isinstance(value, str):
        for old, new in REPLACEMENTS:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    return value


def signature(stage: str, errors: list[dict]) -> str:
    parts = ["phase_a" if stage == "a" else "phase_b"]
    for error in errors[:1]:
        loc = error.get("loc") or []
        field = str(loc[-1]) if loc else "unknown"
        parts.append(str(error.get("type", "error")))
        parts.append(field)
    return "_".join(parts).replace(".", "_")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="覆盖已存在的同名 fixture")
    args = parser.parse_args()

    if not DB.exists():
        raise SystemExit(f"找不到数据库：{DB}")
    FIXTURES.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT stage, error_type, diagnostic_json, created_at FROM model_runs"
        " WHERE status='failed' AND diagnostic_json IS NOT NULL AND diagnostic_json != 'null'"
        " ORDER BY created_at DESC"
    ))
    conn.close()

    written = 0
    seen: set[str] = set()
    for row in rows:
        raw_diagnostic = row["diagnostic_json"]
        try:
            diagnostic = json.loads(raw_diagnostic) if isinstance(raw_diagnostic, str) else None
        except json.JSONDecodeError:
            continue
        if not isinstance(diagnostic, dict):
            continue
        raw = diagnostic.get("raw_model_output")
        if raw is None:
            continue  # 归一化崩溃或早期版本：raw 未留存
        errors = diagnostic.get("validation_errors") or []
        name = signature(row["stage"], errors)
        if name in seen:
            continue
        seen.add(name)
        target = FIXTURES / f"{name}.json"
        if target.exists() and not args.all:
            continue
        target.write_text(json.dumps(sanitize(raw), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        written += 1
        print(f"已固化 {target.name}  （错误：{[(e.get('loc'), e.get('type')) for e in errors[:2]]}）")

    if written:
        print(f"\n共固化 {written} 个坏例。下一步：在 tests/unit/test_badcase_regressions.py 中补断言，")
        print("断言 fixture 仍保留坏法（否则回归失效），并断言修复后的输出符合预期。")
    else:
        print("没有新的坏例需要固化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
