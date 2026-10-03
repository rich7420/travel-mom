from __future__ import annotations
from datetime import datetime
from typing import Any
from app.models import CaseStatus,MomIntentResponse,MomIntentSuggestion,MomIntentRequest
from app.repositories import approval_repo,browser_task_repo,case_repo,flight_search_run_repo,hotel_search_run_repo,preferences_repo
from app.services.case_workflow import case_workflow
from app.services.case_operations import BUSINESS_ZONE, lifecycle_action, list_work_items

def _friendly_case_status(status:str)->str:
    return {"new":"剛建立","intake":"確認需求中","quoting":"查價與報價中","booking":"準備訂購","confirmed":"已確認","travelling":"旅途中","closed":"已完成"}.get(status,"處理中")
def _days_until(value)->int|None:return (value-datetime.now(BUSINESS_ZONE).date()).days if value else None

def next_best_action(case, workflow=None)->dict[str,Any]:
    flight_runs=flight_search_run_repo.list(case_id=case.id,limit=3);hotel_runs=hotel_search_run_repo.list(case_id=case.id,limit=3)
    if case.status==CaseStatus.CLOSED:return {"kind":"case","label":"查看已完成案件","reason":"這個案件已完成","case_id":case.id}
    operation = lifecycle_action(case)
    if operation:
        return operation
    if not case.destination:return {"kind":"edit_case","label":"補上目的地","reason":"先把客人的目的地確認好","case_id":case.id}
    if not case.depart_date:return {"kind":"edit_case","label":"補上出發日期","reason":"有日期後才能可靠查價","case_id":case.id}
    workflow = workflow if workflow is not None else case_workflow(case.id)
    if workflow["can_draft_offer"]:
        return {"kind":"quotes","module":"quotes","label":"建立正式報價","reason":"已選定有效方案，可保存正式報價版本","case_id":case.id}
    if workflow["options"] or workflow["selections"]:
        return {"kind":"case_options","label":"比較與選方案","reason":"核對來源、價格與條件，再選定參考方案","case_id":case.id}
    if not flight_runs:return {"kind":"flight_search","label":"先查機票","reason":"這個案件還沒有機票查價紀錄","case_id":case.id}
    latest=flight_runs[0]
    if not latest.selected_option_id:return {"kind":"flight_run","label":"看機票方案","reason":"已有查價紀錄，但還沒選方案","case_id":case.id,"run_id":latest.id}
    if not hotel_runs:return {"kind":"hotel_search","label":"接著找飯店","reason":"機票已有候選方案，飯店還沒開始","case_id":case.id}
    latest_h=hotel_runs[0]
    if not latest_h.selected_option_id:return {"kind":"hotel_run","label":"看飯店方案","reason":"已有飯店查價，但還沒選房型／方案","case_id":case.id,"run_id":latest_h.id}
    return {"kind":"customer_reply","label":"整理方案回客人","reason":"機票與飯店都有候選方案","case_id":case.id}

def _task_state(task)->dict[str,Any]:
    labels={"queued":"等待查詢","planned":"等待查詢","running":"正在查官方網站","completed":"已完成","complete":"已完成","degraded":"AI 連線不完整","needs_review":"需要確認","manual_required":"需要您幫一下","failed":"這次沒有查完","error":"這次沒有查完"}
    structured=task.result_json.get("status") if isinstance(task.result_json,dict) else None;attention=task.status in {"needs_review","manual_required","failed","error","degraded"};label=labels.get(task.status,"處理中")
    if structured=="manual_required":attention=True;label="需要您幫一下"
    elif structured=="no_results":label="沒有找到符合結果"
    elif structured in {"blocked","error"}:attention=True;label="這次沒有查完"
    return {"id":task.id,"provider_code":task.provider_code,"status":task.status,"structured_status":structured,"label":label,"needs_attention":attention,"review_state":task.review_state}

def search_run_progress(kind:str,run_id:str)->dict[str,Any]:
    if kind=="flight":run=flight_search_run_repo.get(run_id)
    elif kind=="hotel":run=hotel_search_run_repo.get(run_id)
    else:raise ValueError("kind must be flight or hotel")
    if not run:raise KeyError(run_id)
    tasks=browser_task_repo.list(limit=100,search_run_id=run.id);states=[_task_state(t) for t in tasks];completed=sum(1 for i in states if i["status"] in {"completed","complete"});attention=sum(1 for i in states if i["needs_attention"])
    return {"schema_version":"mom-search-progress-v1","kind":kind,"run_id":run.id,"case_id":run.case_id,"status":run.status.value if hasattr(run.status,"value") else str(run.status),"completed":completed,"total":len(states),"attention":attention,"can_leave":True,"tasks":states,"selected_option_id":run.selected_option_id,"updated_at":run.updated_at}

def build_mom_home()->dict[str,Any]:
    prefs=preferences_repo.get();cases=case_repo.list();pending=approval_repo.list("pending");cards=[]
    urgent_cases = {i["case_id"] for i in list_work_items() if i["timing"] in {"overdue", "today"}}
    for case in cases:
        days=_days_until(case.depart_date);urgency=0
        if days is not None:
            if 0<=days<=2:urgency=100
            elif 3<=days<=7:urgency=70
            elif days<0 and case.status not in {CaseStatus.CLOSED,CaseStatus.TRAVELLING}:urgency=90
        if case.status in {CaseStatus.NEW,CaseStatus.INTAKE,CaseStatus.QUOTING}:urgency+=15
        if case.id in urgent_cases:urgency+=200
        cards.append({"id":case.id,"customer_name":case.customer_name,"destination":case.destination or "目的地未定","date_label":f"{case.depart_date.isoformat()} → {case.return_date.isoformat() if case.return_date else '回程未定'}" if case.depart_date else "日期未定","status":_friendly_case_status(case.status.value),"status_code":case.status.value,"days_until_departure":days,"next_action":None,"urgency":urgency,"updated_at":case.updated_at})
    priority=sorted([row for row in cards if row["status_code"] != "closed"],key=lambda r:(r["urgency"],r["updated_at"]),reverse=True)[:4];recent=cards[:6]
    case_by_id = {case.id: case for case in cases}
    for card in priority + recent:
        if card["next_action"] is None:
            card["next_action"] = next_best_action(case_by_id[card["id"]])
    fr=flight_search_run_repo.list(limit=4);hr=hotel_search_run_repo.list(limit=4)
    return {"schema_version":"mom-home-v1","preferences":prefs.model_dump(mode="json"),"counts":{"cases":len(cases),"pending_approvals":len(pending)},"priority":priority,"recent_cases":recent,"resume":recent[0] if recent else None,"searches":{"flight":[search_run_progress("flight",r.id) for r in fr],"hotel":[search_run_progress("hotel",r.id) for r in hr]}}

def infer_mom_intent(req:MomIntentRequest)->MomIntentResponse:
    lower=req.text.strip().lower();matches=[]
    def add(action,label,reason,confidence):matches.append(MomIntentSuggestion(action=action,label=label,reason=reason,confidence=confidence))
    if any(k in lower for k in ["回客","回覆","客人說","太貴","客戶","怎麼回","殺價"]):add("customer_reply","幫我寫回覆","看起來是在處理客戶訊息",.92)
    if any(k in lower for k in ["機票","航班","飛機","華航","國泰","星宇","華信","長榮","阿聯酋","ana","全日空"]):add("flight_search","查機票","訊息裡提到航班或航空公司",.91)
    if any(k in lower for k in ["飯店","酒店","住宿","房型","早餐","check-in","入住"]):add("hotel_search","查飯店","訊息裡提到住宿需求",.90)
    if any(k in lower for k in ["行程","景點","幾日遊","安排","路線"]):add("itinerary","做行程","看起來是在安排行程",.87)
    if any(k in lower for k in ["簽證","入境","visa","護照效期"]):add("visa","查簽證／入境","訊息裡有入境或證件需求",.93)
    if any(k in lower for k in ["新客人","新案件","新增客人"]):add("new_case","建立新客人","看起來要建立新案件",.95)
    if any(k in lower for k in ["那個客人","案件","之前","做到哪","進度"]):add("case_lookup","找案件","看起來要接續之前的工作",.80)
    if not matches:
        matches=[MomIntentSuggestion(action="customer_reply",label="回覆客人",reason="如果這是一段客戶訊息，可以先幫您整理回覆",confidence=.35),MomIntentSuggestion(action="flight_search",label="查機票",reason="如果您正在處理交通，我可以一步一步帶您查",confidence=.30),MomIntentSuggestion(action="hotel_search",label="查飯店",reason="如果您正在處理住宿，我可以先整理條件",confidence=.30),MomIntentSuggestion(action="new_case",label="建立新客人",reason="也可以從一個新案件開始",confidence=.25)]
        return MomIntentResponse(text="沒關係，不用重新想怎麼問。選一個最接近的就好。",suggestions=matches)
    matches.sort(key=lambda r:r.confidence,reverse=True);return MomIntentResponse(text="我大概知道您想做什麼，選一個最接近的就好。",suggestions=matches[:4])
