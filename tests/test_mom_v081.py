from __future__ import annotations

from dataclasses import replace
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.db import connect, init_db
from app.models import TripCaseCreate
from app.repositories import case_repo, preferences_repo, skill_feedback_repo

client = TestClient(app)


def _unique(label: str) -> str:
    import uuid
    return f"{label}-{uuid.uuid4().hex[:8]}"


def test_health_v081_root_strict_csp_admin_legacy_csp():
    with client:
        health = client.get('/health')
        mom = client.get('/')
        admin = client.get('/admin')
    assert health.status_code == 200
    assert health.json()['app_version'] == '0.8.1'
    assert "'unsafe-inline'" not in mom.headers['content-security-policy']
    assert "'unsafe-inline'" in admin.headers['content-security-policy']
    assert 'onclick=' not in mom.text
    assert '旅行社小幫手' in mom.text


def test_preferences_roundtrip_filters_unknown_airlines():
    with client:
        response = client.patch('/api/mom/preferences', json={
            'default_origin': 'khh',
            'preferred_airlines': ['CI', 'JX', 'ZZ', 'NH'],
            'font_scale': 'xlarge',
            'onboarding_complete': True,
        })
        fetched = client.get('/api/mom/preferences')
    assert response.status_code == 200
    body = response.json()
    assert body['default_origin'] == 'KHH'
    assert body['preferred_airlines'] == ['CI', 'JX', 'NH']
    assert body['font_scale'] == 'xlarge'
    assert fetched.json()['default_origin'] == 'KHH'


def test_guided_resume_back_default_origin_and_two_adult_one_child():
    session = _unique('guide')
    # Set a deterministic preference for this workflow.
    client.patch('/api/mom/preferences', json={'default_origin': 'TPE'})
    start = client.post(f'/api/guided/{session}/start?reset=true')
    assert start.status_code == 200
    assert start.json()['progress_total'] == 6
    assert start.json()['can_back'] is False

    assert client.post(f'/api/guided/{session}/reply', json={'text': '陳小姐'}).status_code == 200
    destination = client.post(f'/api/guided/{session}/reply', json={'text': '東京'})
    assert destination.json()['can_back'] is True

    back = client.post(f'/api/guided/{session}/back')
    assert back.status_code == 200
    assert '上一題' in back.json()['text']
    assert back.json()['next_field'] == 'destination'
    client.post(f'/api/guided/{session}/reply', json={'text': '東京'})
    client.post(f'/api/guided/{session}/reply', json={'text': '2026-10-18'})
    client.post(f'/api/guided/{session}/reply', json={'text': '2026-10-22'})
    travelers = client.post(f'/api/guided/{session}/reply', json={'text': '2大1小'})
    assert travelers.status_code == 200
    done = client.post(f'/api/guided/{session}/reply', json={'text': '10萬內'})
    assert done.status_code == 200
    assert done.json()['done'] is True
    case_id = done.json()['case_id']
    trip = client.get(f'/api/cases/{case_id}').json()
    assert trip['origin'] == 'TPE'
    assert trip['adults'] == 2
    assert trip['children'] == 1
    assert trip['budget_twd'] == 100000

    resumed = client.get(f'/api/guided/{session}/resume')
    assert resumed.json()['done'] is True
    assert resumed.json()['case_id'] == case_id


def test_guided_rejects_return_before_departure():
    session = _unique('dates')
    client.post(f'/api/guided/{session}/start?reset=true')
    client.post(f'/api/guided/{session}/reply', json={'text': '林先生'})
    client.post(f'/api/guided/{session}/reply', json={'text': '大阪'})
    client.post(f'/api/guided/{session}/reply', json={'text': '2026-11-10'})
    bad = client.post(f'/api/guided/{session}/reply', json={'text': '2026-11-01'})
    assert bad.status_code == 200
    assert '比出發日期早' in bad.json()['text']
    assert bad.json()['next_field'] == 'return_date'


def test_mom_home_has_next_best_action_for_new_dated_case():
    case = case_repo.create(TripCaseCreate(
        customer_name=_unique('王小姐'), destination='NRT', origin='TPE',
        depart_date='2026-12-10', return_date='2026-12-14', adults=2,
    ))
    case_repo.patch(case.id, {'status': 'quoting'})
    with client:
        detail = client.get(f'/api/mom/cases/{case.id}')
        home = client.get('/api/mom/home')
    assert detail.status_code == 200
    assert detail.json()['next_action']['kind'] == 'flight_search'
    assert home.status_code == 200
    assert any(row['id'] == case.id for row in home.json()['recent_cases'])


def test_mom_intent_assistant_returns_actions_without_prompt_jargon():
    with client:
        response = client.post('/api/mom/intent', json={'text': '客人說機票太貴了，我該怎麼回？'})
    assert response.status_code == 200
    actions = {item['action'] for item in response.json()['suggestions']}
    assert 'customer_reply' in actions
    assert 'flight_search' in actions
    assert 'prompt' not in response.json()['text'].lower()


def test_skill_feedback_redacts_pii_and_fingerprints_skill_without_mutating_it():
    case = case_repo.create(TripCaseCreate(customer_name='測試陳小姐', destination='Tokyo'))
    skill_path = Path(__file__).resolve().parents[1] / 'openclaw' / 'skills' / 'customer-reply' / 'SKILL.md'
    before = skill_path.read_bytes()
    payload = {
        'skill_key': 'customer-reply',
        'feedback_type': 'edited',
        'case_id': case.id,
        'draft_text': '測試陳小姐您好，電話 0912-345-678，email mom@example.com，PNR: ABC123',
        'final_text': '測試陳小姐您好，我先幫您確認兩個方案。',
        'note': '以後不要把客戶電話寫進草稿',
    }
    with client:
        response = client.post('/api/mom/skill-feedback', json=payload)
        summary = client.get('/api/mom/skill-feedback/summary?skill_key=customer-reply')
    assert response.status_code == 200
    body = response.json()
    assert body['skill_hash']
    assert '[CUSTOMER]' in body['draft_redacted']
    assert '[PHONE]' in body['draft_redacted']
    assert '[EMAIL]' in body['draft_redacted']
    assert '[REDACTED]' in body['draft_redacted']
    assert body['possible_pii'] is True
    assert 0 <= body['edit_ratio'] <= 1
    assert summary.status_code == 200
    assert '不會自動修改正式 Skill' in summary.json()['proposal_reason'] or summary.json()['ready_for_proposal'] is True
    assert skill_path.read_bytes() == before


def test_offline_flight_search_start_is_saved_and_resumable_when_openclaw_disabled():
    created = client.post('/api/browser/flight-search', json={
        'origin':'TPE','destination':'NRT','depart_date':'2026-10-18','return_date':'2026-10-22',
        'adults':2,'children':0,'infants':0,'airline_codes':['CI','JX','CX']
    })
    assert created.status_code == 200
    run_id = created.json()['run']['id']
    with client:
        started = client.post(f'/api/mom/flight-search/{run_id}/start')
        progress = client.get(f'/api/mom/search-progress/flight/{run_id}')
    assert started.status_code == 200
    assert started.json()['accepted'] is False
    assert started.json()['reason'] == 'openclaw_disabled'
    assert progress.status_code == 200
    assert progress.json()['total'] == 3
    assert progress.json()['can_leave'] is True


def test_manifest_is_installable_shell_without_service_worker_api_cache():
    with client:
        manifest = client.get('/static/manifest.webmanifest')
        js = client.get('/static/app.js')
    assert manifest.status_code == 200
    body = manifest.json()
    assert body['display'] == 'standalone'
    assert body['start_url'] == '/'
    assert 'serviceWorker' not in js.text
    assert 'caches.open' not in js.text


def test_v081_migration_adds_new_tables_without_dropping_existing_case(monkeypatch, tmp_path):
    import app.db as db_module
    old_settings = db_module.settings
    local_settings = replace(old_settings, db_path=str(tmp_path / 'migration.db'))
    monkeypatch.setattr(db_module, 'settings', local_settings)
    db_module.init_db()
    with db_module.connect() as db:
        db.execute("INSERT INTO trip_cases(id,customer_name,destination,origin,adults,children,notes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ('trip_keep','保留客人','Tokyo','TPE',2,0,'','quoting','2026-08-25T00:00:00Z','2026-08-25T00:00:00Z'))
        db.execute('DROP TABLE user_preferences')
        db.execute('DROP TABLE skill_feedback')
        db.execute('DELETE FROM schema_migrations WHERE version=801')
    db_module.init_db()
    with db_module.connect() as db:
        kept = db.execute("SELECT customer_name FROM trip_cases WHERE id='trip_keep'").fetchone()
        prefs = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_preferences'").fetchone()
        feedback = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='skill_feedback'").fetchone()
        mig = db.execute('SELECT version FROM schema_migrations WHERE version=801').fetchone()
    assert kept['customer_name'] == '保留客人'
    assert prefs and feedback and mig
