from app.db import init_db
from app.services.guided import guided_intake


def test_guided_flow_creates_case():
    init_db()
    sid='test-guided'
    a=guided_intake.start(sid)
    assert a.next_field=='customer_name'
    for text in ['王小姐','東京','2026-10-18','2026-10-22','2 位','10 萬內']:
        a=guided_intake.reply(sid,text)
    assert a.done
    assert a.case_id
    assert '案件建立好了' in a.text
