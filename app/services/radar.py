from __future__ import annotations

from datetime import date

from app.models import RadarItem
from app.repositories import approval_repo, case_repo


def build_radar() -> list[RadarItem]:
    today = date.today()
    items: list[RadarItem] = []
    for c in case_repo.list():
        if c.depart_date:
            days = (c.depart_date - today).days
            if 0 <= days <= 7:
                items.append(RadarItem(severity="red" if days <= 2 else "yellow", case_id=c.id,
                                       title=f"{c.customer_name}・{c.destination or '旅行'}",
                                       detail=f"{days} 天後出發，建議確認機票/飯店與行前資料。",
                                       action="打開案件"))
        if c.status.value in {"new", "intake", "quoting"}:
            items.append(RadarItem(severity="yellow", case_id=c.id, title=f"{c.customer_name}・待處理",
                                   detail="案件尚未完成確認或訂購。", action="繼續處理"))
    pending = approval_repo.list("pending")
    for a in pending:
        if a.case_id:
            items.append(RadarItem(severity="red", case_id=a.case_id, title="有待核准操作", detail=a.summary, action="查看核准"))
    return items[:20]
