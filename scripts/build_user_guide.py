"""Build the checked-in static guide from the Traditional Chinese user manual."""
from __future__ import annotations

import argparse
from html import escape
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/USER_GUIDE_ZH_TW_DRAFT.md"
TEMPLATE = ROOT / "scripts/templates/user_guide.html"
OUTPUT = ROOT / "app/mom_static/guide.html"

# App help links use these stable fragments. Renaming a heading requires updating
# its label here, while retaining the fragment used by the app.
CHAPTER_IDS = {
    "五分鐘開始第一個案件": "start",
    "開啟與第一次設定": "setup",
    "建立與接續案件": "new-case",
    "修改需求與旅客": "edit-case",
    "保存機票與飯店查價需求": "search",
    "錄入實際查到的方案": "manual-options",
    "比較與選方案": "compare",
    "整理與修改客戶回覆": "reply",
    "查價紀錄與今天的工作": "today",
    "常見問題與卡住時怎麼做": "troubleshooting",
    "還需要使用旅行社原本流程的工作": "limits",
}


def render_guide() -> str:
    markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = markdown.parse(SOURCE.read_text(encoding="utf-8"))
    chapters = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2":
            title = tokens[index + 1].content
            chapter_id = CHAPTER_IDS[title]
            token.attrSet("id", f"{chapter_id}-title")
            chapters.append((index, title, chapter_id))
    if len({chapter_id for _, _, chapter_id in chapters}) != len(chapters):
        raise ValueError("Guide chapter fragments must be unique")
    if not chapters:
        raise ValueError("Guide must contain chapters")
    intro = markdown.renderer.render(tokens[:chapters[0][0]], markdown.options, {})
    content, links = [], []
    for number, (start, title, chapter_id) in enumerate(chapters, 1):
        end = chapters[number][0] if number < len(chapters) else len(tokens)
        body = markdown.renderer.render(tokens[start:end], markdown.options, {})
        content.append(f'<section class="guide-chapter" id="{chapter_id}" tabindex="-1" aria-labelledby="{chapter_id}-title">\n{body}</section>')
        links.append(f'<li><a href="#{chapter_id}"><span aria-hidden="true">{number:02}</span>{escape(title)}</a></li>')
    template = TEMPLATE.read_text(encoding="utf-8")
    return (template.replace("{{INTRO}}", intro)
            .replace("{{CONTENTS}}", "\n".join(links))
            .replace("{{CHAPTERS}}", "\n".join(content)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated HTML differs; never write")
    args = parser.parse_args()
    result = render_guide().encode("utf-8")
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != result:
            print("User guide is stale. Run python scripts/build_user_guide.py")
            return 1
        print("User guide matches its Markdown source and template.")
    else:
        OUTPUT.write_bytes(result)
        print("Built app/mom_static/guide.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
