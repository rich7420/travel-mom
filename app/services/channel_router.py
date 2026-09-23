from __future__ import annotations

from app.config import settings
from app.models import ChannelReply
from app.repositories import case_repo, session_repo
from app.services.guided import FIELDS, guided_intake
from app.services.openclaw import openclaw_client
from app.services.radar import build_radar


MAIN_MENU = ["➕ 新客人", "✅ 今日工作", "📂 查案件", "✈️ 找機票", "🏨 找飯店", "💬 問旅行助理"]


def _normalize(text: str) -> str:
    return text.strip().replace("️", "")


def _current_case_id(session_id: str) -> str | None:
    state = session_repo.get(session_id) or {}
    return state.get("case_id")


def _guided_active(session_id: str) -> bool:
    state = session_repo.get(session_id)
    if not state:
        return False
    return int(state.get("index", 0)) < len(FIELDS)


def _menu_reply() -> ChannelReply:
    return ChannelReply(
        text="早安，我是旅行社工作助理。你不用想怎麼問，直接選今天要做的事。",
        options=MAIN_MENU,
        source="menu",
    )


def _radar_reply() -> ChannelReply:
    rows = build_radar()
    if not rows:
        return ChannelReply(text="目前沒有急件。可以先新增客人，或打開案件繼續處理。", options=MAIN_MENU)
    lines = ["今天優先處理："]
    for idx, item in enumerate(rows[:6], start=1):
        icon = "🔴" if item.severity == "red" else "🟡"
        lines.append(f"{idx}. {icon} {item.title}\n{item.detail}")
    return ChannelReply(text="\n\n".join(lines), options=["📂 查案件", "➕ 新客人", "主選單"], source="radar")


def _cases_reply() -> ChannelReply:
    rows = case_repo.list()[:6]
    if not rows:
        return ChannelReply(text="目前還沒有案件。要先新增一位客人嗎？", options=["➕ 新客人", "主選單"])
    lines = ["最近案件："]
    for idx, case in enumerate(rows, start=1):
        dates = f"{case.depart_date or '日期未定'}～{case.return_date or '未定'}"
        lines.append(f"{idx}. {case.customer_name}・{case.destination or '目的地未定'}\n{dates}・{case.status.value}")
    lines.append(f"\n完整案件面板：{settings.public_base_url}")
    return ChannelReply(text="\n\n".join(lines), options=["✅ 今日工作", "➕ 新客人", "主選單"], source="cases")


async def route_channel_message(session_id: str, text: str) -> ChannelReply:
    normalized = _normalize(text)

    if normalized in {"/start", "開始", "主選單", "選單", "menu"}:
        return _menu_reply()
    if normalized in {"取消", "離開", "exit"}:
        session_repo.clear(session_id)
        return ChannelReply(
            text="已取消目前的引導流程。沒有建立新案件。",
            options=MAIN_MENU,
            source="cancelled",
        )
    if normalized in {"➕ 新客人", "新客人", "新增案件"}:
        ans = guided_intake.start(session_id)
        return ChannelReply(text=ans.text, options=ans.options, case_id=ans.case_id, source="guided")

    if _guided_active(session_id):
        ans = guided_intake.reply(session_id, text)
        return ChannelReply(text=ans.text, options=ans.options, case_id=ans.case_id, source="guided")

    if normalized in {"✅ 今日工作", "今日工作", "今天要做什麼", "工作雷達"}:
        return _radar_reply()
    if normalized in {"📂 查案件", "查案件", "案件"}:
        return _cases_reply()

    case_id = _current_case_id(session_id)
    if normalized in {"✈ 找機票", "找機票", "查機票"}:
        suffix = f"目前綁定案件：{case_id}。" if case_id else "目前沒有綁定案件，建議先新增客人。"
        return ChannelReply(
            text=f"{suffix}\n請打開案件面板，系統會用華航、國泰、星宇、華信、阿聯酋、ANA 的官方網站流程建立查票任務：\n{settings.public_base_url}",
            options=["📂 查案件", "➕ 新客人", "主選單"],
            case_id=case_id,
            source="flight-entry",
        )
    if normalized in {"🏨 找飯店", "找飯店", "查飯店"}:
        return ChannelReply(
            text="飯店官網流程仍在下一階段開發。目前可以先把客人的地點、星級、預算、交通與取消需求告訴我，我會整理成搜尋條件。",
            options=["💬 問旅行助理", "📂 查案件", "主選單"],
            case_id=case_id,
            source="hotel-entry",
        )
    if normalized in {"💬 問旅行助理", "問旅行助理", "問助理"}:
        return ChannelReply(
            text="把客戶的問題、訊息或你卡住的事情直接貼過來。我會先做草稿，不會自己傳送、付款或開票。",
            options=["主選單"],
            case_id=case_id,
            source="agent-entry",
        )

    trip = case_repo.get(case_id) if case_id else None
    context = f"TripCase: {trip.model_dump(mode='json') if trip else 'none'}"
    reply = await openclaw_client.ask(
        text,
        session_user=f"channel:{session_id}",
        extra_context=context + "\n這是媽媽透過聊天介面提出的問題；請用簡短繁體中文，一次只引導一個下一步。",
    )
    return ChannelReply(
        text=reply.text,
        options=["主選單", "✅ 今日工作", "📂 查案件"],
        case_id=case_id,
        source=reply.source,
    )
