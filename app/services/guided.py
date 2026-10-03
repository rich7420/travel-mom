from __future__ import annotations

import re
from datetime import date

from pydantic import ValidationError

from app.models import CaseStatus, GuidedReply, TripCaseCreate
from app.repositories import case_repo, preferences_repo, session_repo

FIELDS = ["customer_name", "destination", "depart_date", "return_date", "travelers", "budget_twd"]
PROMPTS = {
    "customer_name": ("這是哪一位客人的案件？請直接輸入稱呼。", []),
    "destination": ("想去哪裡？城市或國家都可以。", ["日本", "韓國", "歐洲", "東南亞", "還沒決定"]),
    "depart_date": ("大概哪一天出發？", ["日期還沒確定"]),
    "return_date": ("預計哪一天回來？", ["回程還沒確定"]),
    "travelers": ("幾位旅客？例如「2大1小」，有嬰兒可說「2大1小1嬰兒」。", ["1 位成人", "2 位成人", "2大1小", "2大2小"]),
    "budget_twd": ("有總預算嗎？沒有也沒關係。", ["先不設預算", "5 萬內", "10 萬內", "20 萬內"]),
}


def _parse_date(text: str) -> str | None:
    try:
        return date.fromisoformat(text.strip().replace("/", "-")).isoformat()
    except ValueError:
        return None


def _parse_travelers(text: str) -> tuple[int, int, int] | None:
    value = text.strip().lower().replace("位", "")
    adult = re.search(r"(\d+)\s*(?:大|成人|adult)", value)
    child = re.search(r"(\d+)\s*(?:小|兒童|child)", value)
    infant = re.search(r"(\d+)\s*(?:嬰兒|嬰|infant)", value)
    if adult or child or infant:
        party = (int(adult.group(1)) if adult else 1, int(child.group(1)) if child else 0, int(infant.group(1)) if infant else 0)
    elif re.fullmatch(r"\d+\s*(?:人|個人)?", value):
        party = (int(re.search(r"\d+", value).group()), 0, 0)
    else:
        return None
    adults, children, infants = party
    return party if 1 <= adults <= 50 and 0 <= children <= 50 and 0 <= infants <= min(20, adults) else None


def _parse_budget(text: str) -> int | None:
    value = text.replace(",", "").replace("元", "").strip()
    if any(word in value for word in ["不設", "沒有", "先不"]):
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*萬(?:內)?", value)
    amount = int(float(match.group(1)) * 10000) if match else int(value)
    if amount < 0:
        raise ValueError("預算不可小於 0")
    return amount


def _reply(*, text: str, options: list[str] | None = None, index: int = 0, done: bool = False, case_id: str | None = None, next_field: str | None = None) -> GuidedReply:
    return GuidedReply(text=text, options=options or [], progress_current=min(index + (0 if done else 1), len(FIELDS)), progress_total=len(FIELDS), done=done, case_id=case_id, next_field=next_field, can_back=index > 0 and not done, saved=True)


class GuidedIntake:
    def start(self, session_id: str, *, reset: bool = False) -> GuidedReply:
        previous = session_repo.get(session_id)
        if not reset and previous and not previous.get("done"):
            return self.resume(session_id)
        session_repo.put(session_id, None, {"index": 0, "answers": {}, "case_id": None, "done": False})
        return self.resume(session_id)

    def resume(self, session_id: str) -> GuidedReply:
        state = session_repo.get(session_id)
        if not state:
            return self.start(session_id, reset=True)
        if state.get("done") or int(state.get("index", 0)) >= len(FIELDS):
            case_id = state.get("case_id")
            case = case_repo.get(case_id) if case_id else None
            title = f"{case.customer_name} 的 {case.destination or '旅行'}案件" if case else "案件"
            return _reply(text=f"{title}建立好了。接下來想先做什麼？", options=["✈️ 找機票", "🏨 找飯店", "💬 回客戶"], index=len(FIELDS), done=True, case_id=case_id)
        index = max(0, min(int(state.get("index", 0)), len(FIELDS) - 1))
        field = FIELDS[index]
        prompt, options = PROMPTS[field]
        return _reply(text=prompt, options=options, index=index, next_field=field)

    def back(self, session_id: str) -> GuidedReply:
        state = session_repo.get(session_id)
        if not state:
            return self.start(session_id, reset=True)
        if state.get("done") or state.get("case_id"):
            return _reply(text="案件已建立。如果要改資料，請直接打開案件修改，避免產生重複案件。", options=["打開案件"], index=len(FIELDS), done=True, case_id=state.get("case_id"))
        index = int(state.get("index", 0))
        if index <= 0:
            return self.resume(session_id)
        index -= 1
        answers = dict(state.get("answers", {}))
        field = FIELDS[index]
        for key in (["adults", "children", "infants"] if field == "travelers" else [field]):
            answers.pop(key, None)
        state.update(index=index, answers=answers)
        session_repo.put(session_id, None, state)
        result = self.resume(session_id)
        result.text = "好，我們回上一題。" + result.text
        return result

    def save(self, session_id: str) -> GuidedReply:
        result = self.resume(session_id)
        result.text = "已經幫您存好了。下次回來可以從這裡繼續。\n\n" + result.text
        return result

    def reset(self, session_id: str) -> GuidedReply:
        return self.start(session_id, reset=True)

    def reply(self, session_id: str, text: str) -> GuidedReply:
        state = session_repo.get(session_id)
        if not state:
            return self.start(session_id, reset=True)
        index = int(state.get("index", 0))
        if state.get("done") or index >= len(FIELDS):
            return self.resume(session_id)
        field = FIELDS[index]
        answers = dict(state.get("answers", {}))
        cleaned = text.strip()
        prompt, options = PROMPTS[field]
        def invalid(message: str) -> GuidedReply:
            return _reply(text=message + "\n" + prompt, options=options, index=index, next_field=field)
        if not cleaned:
            return invalid("這題還沒有填。")
        if field == "customer_name" and len(cleaned) > 80:
            return invalid("客人稱呼請填 80 個字以內。")
        if field in {"depart_date", "return_date"}:
            value = _parse_date(cleaned)
            if value is None and cleaned not in {"日期還沒確定", "回程還沒確定", "未定", "還沒確定", "單程"}:
                return invalid("日期我沒有看懂，請輸入 YYYY-MM-DD 或選日期還沒確定。")
            if field == "return_date" and value and answers.get("depart_date") and value < answers["depart_date"]:
                return invalid("回程日期比出發日期早，我先不存。")
            answers[field] = value
        elif field == "travelers":
            party = _parse_travelers(cleaned)
            if party is None:
                return invalid("請填實際成人、小孩與嬰兒人數，成人 1–50 位，嬰兒不可多於成人。")
            answers["adults"], answers["children"], answers["infants"] = party
        elif field == "budget_twd":
            try:
                answers[field] = _parse_budget(cleaned)
                if answers[field] is not None and answers[field] > 1_000_000_000:
                    raise ValueError("budget too large")
            except (ValueError, OverflowError):
                return invalid("預算請填非負整數、例如 10萬內，或選先不設預算。")
        else:
            answers[field] = None if field == "destination" and cleaned == "還沒決定" else cleaned
        index += 1
        if index == len(FIELDS):
            try:
                data = TripCaseCreate(**answers, origin=preferences_repo.get().default_origin)
            except ValidationError:
                return invalid("案件資料需要再確認，請使用上一步更正。")
            case = case_repo.create(data)
            case_repo.patch(case.id, {"status": CaseStatus.QUOTING})
            session_repo.put(session_id, case.id, {"index": index, "answers": answers, "case_id": case.id, "done": True})
        else:
            session_repo.put(session_id, None, {"index": index, "answers": answers, "case_id": None, "done": False})
        return self.resume(session_id)


guided_intake = GuidedIntake()
