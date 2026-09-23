#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "openclaw" / "skills"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BROWSER_SAFETY_SKILLS = {"airline-official-search", "price-revalidation", "booking-preflight"}


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    try:
        block = text.split("---\n", 2)[1]
    except IndexError:
        return {}
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def main() -> int:
    errors: list[str] = []
    names: set[str] = set()
    files = sorted(ROOT.glob("*/SKILL.md"))
    if not files:
        errors.append("no local skills found")

    for path in files:
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(path)
        name = meta.get("name", "")
        description = meta.get("description", "")
        user_invocable = meta.get("user-invocable", "")

        if not name:
            errors.append(f"{path}: missing name")
        if not description:
            errors.append(f"{path}: missing description")
        if name and not NAME_RE.fullmatch(name):
            errors.append(f"{path}: invalid name {name!r}")
        if name and name != path.parent.name:
            errors.append(f"{path}: frontmatter name must match directory ({path.parent.name})")
        if len(description) > 160:
            errors.append(f"{path}: description too long ({len(description)} > 160)")
        if user_invocable not in {"true", "false"}:
            errors.append(f"{path}: user-invocable must be true or false")
        if name in names:
            errors.append(f"duplicate skill name: {name}")
        names.add(name)

        if name in BROWSER_SAFETY_SKILLS:
            lowered = text.lower()
            for token in ("payment", "otp", "3ds", "captcha"):
                if token not in lowered:
                    errors.append(f"{path}: browser safety skill missing hard-stop token {token!r}")
        if name in {"browser-lab-reviewer", "site-change-proposal"} and "admin-only" not in text.lower():
            errors.append(f"{path}: maintenance skill must be marked admin-only")

    if errors:
        for error in errors:
            print("ERROR:", error)
        return 1
    print(f"OK: {len(files)} local skills audited")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
