"""Render only whitelisted customer data. URLs are displayed, never fetched."""
from html import escape
from datetime import datetime, timezone

from app.db import connect
from app.operations_repository import OperationConflict, fingerprint, record
from app.repositories import _case_from_row
from app.services.case_operations import accepted_quote, pack_blockers, pack_source, public_pack, public_quote, snapshot, trip_matches
from app.services.case_workflow import _money, _taipei_time
from decimal import Decimal


def customer_document(case_id: str, record_id: str, kind: str) -> str:
    with connect() as db:
        db.execute("BEGIN")
        value = record(db, "quotes" if kind == "quote" else "pretrip", case_id, record_id)
        if kind == "quote":
            safe = public_quote(value)
            case = _case_from_row(db.execute("SELECT * FROM trip_cases WHERE id=?", (case_id,)).fetchone())
            outdated = value["status"] in {"replaced", "rejected"} or not trip_matches(value["case_snapshot"], snapshot(case)) or datetime.fromisoformat(value["valid_until"]) <= datetime.now(timezone.utc)
            warning = "報價歷史版本或已失效，需核對目前有效版本。" if outdated else ""
            body = f"<p>報價版本：{safe['version']} · 有效至 {escape(_taipei_time(safe['valid_until']))}</p>"
            for item in safe["items"]:
                body += f"<section><h2>{escape(item['title'])}</h2><p>{escape(item['details'])}</p><p>{escape(item['conditions'])}</p><p>{escape(item['currency'])} {escape(_money(Decimal(item['total_amount']),item['currency']))}</p></section>"
            for a in safe["adjustments"]:
                body += f"<p>{escape(a['currency'])} 服務費 {escape(a['service_fee'])}；折扣 {escape(a['discount'])}</p>"
            body += "<h2>報價總額（不同幣別不換算）</h2>" + "".join(f"<p>{escape(c)} {escape(_money(Decimal(n),c))}</p>" for c, n in safe["totals"].items())
            body += f"<h2>包含</h2><p>{escape(safe['includes'])}</p><h2>不包含／待確認</h2><p>{escape(safe['excludes'])}</p><p>價格與庫存需在訂購前再次核對。此報價不代表已保留、訂購或付款。</p>"
        else:
            if value["status"] not in {"prepared", "delivered"}:
                raise OperationConflict("行前摘要尚有缺件，請補齊後產生新版，草稿不可複製或列印")
            quote = accepted_quote(db, case_id)
            case = _case_from_row(db.execute("SELECT * FROM trip_cases WHERE id=?", (case_id,)).fetchone())
            source = pack_source(db, case, quote)
            if value["source_hash"] != fingerprint(source):
                raise OperationConflict("行前摘要來源已變更，請重新產生，舊版不可複製或列印")
            safe = public_pack(value)
            warning = ""
            body = f"<p>行前摘要版本：{safe['version']} · 核對報價版本：{safe['quote_version']}</p>"
            body += "".join(f"<p class='warning'>{escape(b)}</p>" for b in safe["blockers"])
            for booking in safe["bookings"]:
                body += f"<section><h2>{escape(booking['title'])}</h2><p>確認號：{escape(booking['confirmation_number'])}</p><p>{escape(booking['customer_details'])}</p></section>"
            for doc in safe["documents"]:
                link = f'<a href="{escape(doc["customer_url"],quote=True)}" rel="noopener noreferrer">開啟文件</a>' if doc["customer_url"] else ""
                body += f"<section><h2>{escape(doc['title'])}</h2><p>{escape(doc['customer_text'])}</p>{link}</section>"
            body += "<p>此摘要整理人工核對內容與文件連結，不會自動附上或合併電子機票／確認單原檔。請一併提供實際文件。</p>"
    trip = safe["case_snapshot"]
    header = f"<p>{escape(trip['customer_name'])} · {escape(trip['destination'] or '目的地待確認')}</p><p>{escape(trip['depart_date'] or '日期待確認')} → {escape(trip['return_date'] or '單程／回程待確認')}；{trip['adults']} 成人、{trip['children']} 小孩、{trip['infants']} 嬰兒</p>"
    return f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(safe['title'])}</title><link rel="stylesheet" href="/static/document.css"><script src="/static/document.js" defer></script></head><body><div class="document-tools"><button id="printDocument" type="button">列印／存成 PDF</button><button id="copyDocument" type="button">複製對客文字</button><p id="copyStatus" role="status"></p></div><main id="customerDocument"><h1>{escape(safe['title'])}</h1>{header}<p class="warning">{escape(warning)}</p>{body}</main></body></html>'''
