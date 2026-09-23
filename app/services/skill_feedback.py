from __future__ import annotations
import difflib,hashlib,re
from pathlib import Path
from app.models import SkillFeedbackCreate,SkillFeedbackRecord,new_id,now_iso
from app.repositories import case_repo,skill_feedback_repo
_PATTERNS=[
(re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",re.I),"[EMAIL]"),
(re.compile(r"(?<!\d)(?:\+?886[-\s]?)?0?9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"),"[PHONE]"),
(re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),"[LONG_NUMBER]"),
(re.compile(r"(?i)(PNR|訂位代號|訂位編號|booking\s*(?:reference|ref))\s*[:：#]?\s*[A-Z0-9]{5,10}"),r"\1：[REDACTED]"),
(re.compile(r"(?i)(ticket\s*(?:number|no\.?|#)|票號|電子機票號碼)\s*[:：#]?\s*[0-9-]{8,20}"),r"\1：[REDACTED]"),
(re.compile(r"(?i)(passport|護照(?:號碼|號)?)\s*[:：#]?\s*[A-Z0-9]{5,16}"),r"\1：[REDACTED]"),]
_PII_HINTS=("護照","身分證","信用卡","卡號","cvv","cvc","生日","出生日期","電話","手機","email","e-mail","訂位代號","pnr")
def redact_feedback_text(text:str|None)->tuple[str|None,bool]:
    if text is None:return None,False
    value=str(text);possible=any(h in value.lower() for h in _PII_HINTS)
    for pattern,replacement in _PATTERNS:
        value,count=pattern.subn(replacement,value);possible=possible or bool(count)
    return value[:16000],possible
def edit_ratio(draft:str|None,final:str|None)->float|None:
    if draft is None or final is None:return None
    if draft==final:return 0.0
    return round(max(0.0,min(1.0,1.0-difflib.SequenceMatcher(a=draft,b=final).ratio())),4)
def _skill_hash(skill_key:str)->str|None:
    path=Path(__file__).resolve().parents[2]/"openclaw"/"skills"/skill_key/"SKILL.md"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
def capture_skill_feedback(data:SkillFeedbackCreate)->SkillFeedbackRecord:
    draft_source,final_source,note_source=data.draft_text,data.final_text,data.note;name_redacted=False
    if data.case_id:
        trip=case_repo.get(data.case_id)
        if trip and trip.customer_name:
            vals=[draft_source,final_source,note_source]
            for i,v in enumerate(vals):
                if v and trip.customer_name in v:vals[i]=v.replace(trip.customer_name,"[CUSTOMER]");name_redacted=True
            draft_source,final_source,note_source=vals
    draft,a=redact_feedback_text(draft_source);final,b=redact_feedback_text(final_source);note,c=redact_feedback_text(note_source)
    record=SkillFeedbackRecord(id=new_id("sfb"),skill_key=data.skill_key.strip().lower(),feedback_type=data.feedback_type,case_id=data.case_id,source=data.source,draft_redacted=draft,final_redacted=final,note_redacted=note,skill_hash=_skill_hash(data.skill_key.strip().lower()),edit_ratio=edit_ratio(draft,final),possible_pii=name_redacted or a or b or c,created_at=now_iso())
    return skill_feedback_repo.create(record)
