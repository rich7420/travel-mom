#!/usr/bin/env python3
"""Export redacted Skill feedback evidence as JSONL for offline evaluation.

This script never exports raw draft/final/note fields because the database stores only
redacted copies for this evidence stream. It does not modify any OpenClaw Skill.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from app.db import init_db
from app.repositories import skill_feedback_repo


def main() -> int:
    parser = argparse.ArgumentParser(description="Export redacted Mom Travel Desk Skill feedback")
    parser.add_argument("--skill", default=None, help="optional skill key, e.g. customer-reply")
    parser.add_argument("--output", default="./data/skill-feedback.jsonl")
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()

    init_db()
    rows = skill_feedback_repo.list(skill_key=args.skill, limit=max(1, min(args.limit, 50000)))
    rows = list(reversed(rows))  # chronological training/evaluation material
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n")

    summary = skill_feedback_repo.summary(skill_key=args.skill)
    print(json.dumps({"output": str(output), "rows": len(rows), "summary": summary.model_dump(mode="json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
