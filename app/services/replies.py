from __future__ import annotations

from app.models import AgentReply, CustomerReplyRequest
from app.config import settings
from app.repositories import case_repo
from app.services.openclaw import openclaw_client
from app.services.case_workflow import case_workflow, local_customer_draft


async def draft_customer_reply(req: CustomerReplyRequest) -> AgentReply:
    workflow = case_workflow(req.case_id) if req.case_id else None
    local_draft = local_customer_draft(req.case_id, req.incoming_text, workflow)
    # Structured offer text and arithmetic stay deterministic even with an AI provider.
    # A failed optional provider must never become a customer-facing configuration message.
    if not settings.openclaw_enabled or (workflow and workflow["selections"]):
        return AgentReply(text=local_draft, source="template", degraded=False)
    trip = case_repo.get(req.case_id) if req.case_id else None
    context = f"案件資料：{trip.model_dump(mode='json') if trip else '沒有綁定案件'}"
    prompt = f"""請幫旅行社業務產生『草稿』，不要真的傳送。
客戶訊息：{req.incoming_text}
語氣：{req.tone}
若客戶問到價格、機位、房況、簽證等即時資訊，而案件沒有可驗證資料，請不要編造，改成清楚說需要幫他確認。
輸出直接可貼給客戶的繁體中文，不要解釋你的思考。"""
    result = await openclaw_client.ask(prompt, session_user=f"customer-reply:{req.case_id or 'adhoc'}", extra_context=context)
    return AgentReply(text=local_draft, source="template", degraded=False) if result.degraded or not result.text.strip() else result
