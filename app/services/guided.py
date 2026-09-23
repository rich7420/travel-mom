from __future__ import annotations
import re
from datetime import date
from app.models import CaseStatus, GuidedReply, TripCaseCreate
from app.repositories import case_repo, preferences_repo, session_repo

FIELDS=["customer_name","destination","depart_date","return_date","travelers","budget_twd"]
PROMPTS={
"customer_name":("這是哪一位客人的案件？",["新客人，直接輸入名字"]),
"destination":("想去哪裡？城市或國家都可以。",["日本","韓國","歐洲","東南亞","還沒決定"]),
"depart_date":("大概哪一天出發？",["日期還沒確定"]),
"return_date":("預計哪一天回來？",["回程還沒確定"]),
"travelers":("幾位旅客？有小孩也可以直接說「2大1小」。",["1 位成人","2 位成人","2大1小","2大2小","團體"]),
"budget_twd":("有總預算嗎？沒有也沒關係。",["先不設預算","5 萬內","10 萬內","20 萬內"]),}

def _parse_date(text:str)->str|None:
    try:return date.fromisoformat(text.strip().replace("/","-")).isoformat()
    except ValueError:return None

def _parse_travelers(text:str)->tuple[int,int]:
    t=text.strip().lower().replace("位",""); adult=re.search(r"(\d+)\s*(?:大|成人|adult)",t); child=re.search(r"(\d+)\s*(?:小|兒童|child)",t)
    if adult or child:return max(1,int(adult.group(1)) if adult else 1),max(0,int(child.group(1)) if child else 0)
    if "團" in t:return 10,0
    nums=[int(x) for x in re.findall(r"\d+",t)]; return (max(1,nums[0]),0) if nums else (2,0)

def _parse_budget(text:str)->int|None:
    t=text.replace(",","").replace("元","").strip()
    if any(k in t for k in ["不設","沒有","先不"]):return None
    m=re.search(r"(\d+(?:\.\d+)?)\s*萬",t)
    if m:return int(float(m.group(1))*10000)
    try:return int(t)
    except ValueError:return None

def _reply(*,text:str,options:list[str]|None=None,index:int=0,done:bool=False,case_id:str|None=None,next_field:str|None=None)->GuidedReply:
    return GuidedReply(text=text,options=options or [],done=done,case_id=case_id,next_field=next_field,progress_current=min(index+(0 if done else 1),len(FIELDS)),progress_total=len(FIELDS),can_back=(index>0 and not done),saved=True)

class GuidedIntake:
    def start(self,session_id:str,*,reset:bool=False)->GuidedReply:
        if not reset and session_repo.get(session_id):return self.resume(session_id)
        state={"index":0,"answers":{},"case_id":None,"done":False}; session_repo.put(session_id,None,state); text,opts=PROMPTS[FIELDS[0]]; return _reply(text=text,options=opts,index=0,next_field=FIELDS[0])
    def resume(self,session_id:str)->GuidedReply:
        state=session_repo.get(session_id)
        if not state:return self.start(session_id,reset=True)
        if state.get("done") or int(state.get("index",0))>=len(FIELDS):
            case_id=state.get("case_id"); case=case_repo.get(case_id) if case_id else None; title=f"{case.customer_name} 的 {case.destination or '旅行'}案件" if case else "案件"
            return _reply(text=f"{title}已經建立好了。接下來想先做什麼？",options=["✈️ 找機票","🏨 找飯店","🗺️ 做行程","💬 回客戶","🤷 你幫我決定"],index=len(FIELDS),done=True,case_id=case_id)
        idx=max(0,min(int(state.get("index",0)),len(FIELDS)-1)); field=FIELDS[idx]; prompt,opts=PROMPTS[field]; return _reply(text=prompt,options=opts,index=idx,next_field=field,case_id=state.get("case_id"))
    def back(self,session_id:str)->GuidedReply:
        state=session_repo.get(session_id)
        if not state:return self.start(session_id,reset=True)
        if state.get("done") or state.get("case_id"):return _reply(text="案件已建立。如果要改資料，請直接打開案件修改，避免產生重複案件。",options=["打開案件"],index=len(FIELDS),done=True,case_id=state.get("case_id"))
        idx=int(state.get("index",0))
        if idx<=0:return self.resume(session_id)
        idx-=1; answers=dict(state.get("answers",{})); field=FIELDS[idx]
        if field=="travelers":answers.pop("adults",None);answers.pop("children",None)
        else:answers.pop(field,None)
        state["index"]=idx;state["answers"]=answers;session_repo.put(session_id,None,state);prompt,opts=PROMPTS[field];return _reply(text=f"好，我們回上一題。{prompt}",options=opts,index=idx,next_field=field)
    def save(self,session_id:str)->GuidedReply:
        current=self.resume(session_id); current.text="已經幫您存好了。下次回來可以從這裡繼續。\n\n"+current.text; return current
    def reset(self,session_id:str)->GuidedReply:
        session_repo.clear(session_id);return self.start(session_id,reset=True)
    def reply(self,session_id:str,text:str)->GuidedReply:
        state=session_repo.get(session_id)
        if not state:return self.start(session_id,reset=True)
        idx=int(state.get("index",0))
        if state.get("done") or idx>=len(FIELDS):return self.resume(session_id)
        field=FIELDS[idx];answers=dict(state.get("answers",{}));cleaned=text.strip();prompt,opts=PROMPTS[field]
        if not cleaned:return _reply(text="這題還沒有填。"+prompt,options=opts,index=idx,next_field=field)
        if field=="depart_date":
            value=_parse_date(cleaned)
            if not value and "沒" not in cleaned and "未" not in cleaned:return _reply(text="日期我沒有看懂。可以輸入 2026-10-18，或按「日期還沒確定」。",options=opts,index=idx,next_field=field)
            answers[field]=value
        elif field=="return_date":
            value=_parse_date(cleaned)
            if not value and "沒" not in cleaned and "未" not in cleaned:return _reply(text="回程日期我沒有看懂。可以輸入 2026-10-22，或按「回程還沒確定」。",options=opts,index=idx,next_field=field)
            depart=answers.get("depart_date")
            if value and depart and value<depart:return _reply(text="回程日期比出發日期早，我先不存。請再確認一次。",options=opts,index=idx,next_field=field)
            answers[field]=value
        elif field=="travelers":answers["adults"],answers["children"]=_parse_travelers(cleaned)
        elif field=="budget_twd":answers[field]=_parse_budget(cleaned)
        elif field=="destination":answers[field]=None if "還沒" in cleaned else cleaned
        else:answers[field]=cleaned
        idx+=1;state={"index":idx,"answers":answers,"case_id":state.get("case_id"),"done":False}
        if idx>=len(FIELDS):
            prefs=preferences_repo.get();data=TripCaseCreate(customer_name=answers["customer_name"],destination=answers.get("destination"),origin=prefs.default_origin,depart_date=answers.get("depart_date"),return_date=answers.get("return_date"),adults=answers.get("adults",2),children=answers.get("children",0),budget_twd=answers.get("budget_twd"));case=case_repo.create(data);case_repo.patch(case.id,{"status":CaseStatus.QUOTING});state["case_id"]=case.id;state["done"]=True;session_repo.put(session_id,case.id,state)
            return _reply(text=f"好，{case.customer_name} 的 {case.destination or '旅行'}案件建立好了。接下來想先做什麼？",options=["✈️ 找機票","🏨 找飯店","🗺️ 做行程","💬 回客戶","🤷 你幫我決定"],index=len(FIELDS),done=True,case_id=case.id)
        session_repo.put(session_id,state.get("case_id"),state);nxt=FIELDS[idx];prompt,opts=PROMPTS[nxt];return _reply(text=prompt,options=opts,index=idx,next_field=nxt)

guided_intake=GuidedIntake()
