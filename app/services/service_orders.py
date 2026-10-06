"""Manual service work orders; supplier facts and actual cash are distinct evidence."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

from app.db import connect
from app.models import now_iso
from app.operations_repository import command, fingerprint, new_record, record, rows, save
from app.repositories import _case_from_row
from app.services import case_operations as ops

from app.services.service_order_state import (TERMINAL, CASH_KINDS, linked_entries, cash_state,
                                             trip_pending, final_dues, ended_trip, financial_current)
AMOUNT_FIELDS = (*CASH_KINDS, 'supplier_fee', 'agency_fee', 'final_customer_due')
TERMINAL_NOTES = {'note', 'contact_supplier', 'contact_customer', 'correction'}


def evidence(data, actor):
    return {'reference': data.reference, 'occurred_at': data.occurred_at.isoformat(), 'actor': actor}


def target_state(db, case, order):
    quote = next((q for q in rows(db, 'quotes', case.id) if q['status'] == 'accepted'), None)
    bookings = [record(db, 'bookings', case.id, bid) for bid in order['booking_ids']]
    travellers = [(t['id'], t['revision'], t['status']) for t in rows(db, 'travellers', case.id)]
    return fingerprint({'trip': ops.snapshot(case), 'quote': [quote['id'], quote['version']] if quote else None,
                        'bookings': [(b['id'], b['revision'], b['status']) for b in bookings], 'travellers': travellers})


def approved(order):
    assessment, decision = order.get('assessment'), order.get('decision')
    return bool(assessment and decision and decision['decision'] == 'approved'
                and decision['assessment_revision'] == assessment['revision'])


def result_current(db, case, order):
    result = order.get('supplier_result')
    if not result or result['outcome'] != 'confirmed':
        return False
    if order['kind'] == 'cancellation':
        return all(record(db, 'bookings', case.id, bid)['status'] == 'voided' for bid in order['booking_ids'])
    if order['kind'] != 'change':
        return True
    quote = next((q for q in rows(db, 'quotes', case.id) if q['status'] == 'accepted'), None)
    if not quote:
        return False
    for bid, revision in order.get('result_bindings', result['result_bookings']).items():
        booking = record(db, 'bookings', case.id, bid)
        if not (booking['status'] == 'confirmed' and booking['revision'] == revision
                and booking['quote_id'] == quote['id'] and ops.trip_matches(booking['case_snapshot'], ops.snapshot(case))):
            return False
    return bool(order.get('result_bindings', result['result_bookings']))


def blockers(db, case, order, ledger):
    cash = cash_state(order, ledger)
    immediate = order['kind'] == 'incident' and not order.get('assessment')
    if immediate:
        return [] if any(event['action'] == 'safety_assistance' for event in order['history']) and not linked_entries(order, ledger) else ['請先記錄實際立即協助；有款項時須先核對方案']
    result = order.get('supplier_result')
    problems = []
    if not order.get('execution'):
        problems.append('尚未記錄本次開始處理')
    if not approved(order):
        problems.append('尚未記錄客人採用目前核對方案')
    if not result:
        problems.append('尚未記錄供應商實際處理結果')
    elif result['outcome'] == 'confirmed' and not result_current(db, case, order):
        problems.append('實際訂購結果已變更，請重新核對異動結果；原供應商通知仍保留')
    if result and result['outcome']=='declined' and order['assessment']['revision']<=result.get('assessment_revision',0):
        problems.append('供應商未能承辦，請核對修正方案並重新記錄客人決定')
    quote_id = next((q['id'] for q in rows(db,'quotes',case.id) if q['status']=='accepted'),None)
    if (order.get('assessment') or {}).get('amounts') and order['assessment'].get('quote_id') != quote_id:
        problems.append('採用報價已變更，請重新核對整案最後應收與客人決定')
    if not cash['current']:
        problems.append('實際收退款尚未與各幣別核對金額一致')
    if order['kind'] == 'change' and result and result['outcome'] == 'confirmed':
        quote = next((q for q in rows(db, 'quotes', case.id) if q['status'] == 'accepted'), None)
        if quote:
            source = ops.pack_source(db, case, quote)
            problems.extend(ops.pack_blockers(source, quote))
            if order.get('had_delivered_pack') and not any(p['status'] == 'delivered' and p['source_hash'] == fingerprint(source) for p in rows(db, 'pretrip', case.id)):
                problems.append('原行前資料已交付，請重新交付目前有效新版')
    return problems


def view(db, case, order, ledger=None):
    ledger = ledger if ledger is not None else rows(db, 'ledger', case.id)
    assessment = order.get('assessment')
    current = bool(assessment and assessment['source_state'] == target_state(db, case, order))
    expired = bool(assessment and datetime.fromisoformat(assessment['valid_until']) <= datetime.now(timezone.utc))
    terminal = order['status'] in TERMINAL
    actions = []
    if case.status.value != 'closed':
        if terminal:
            actions = ['note', 'reopen']
        else:
            actions = ['edit', 'note', 'assess', 'resolve']
            if order['kind']=='change' and (order.get('supplier_result') or {}).get('outcome')=='confirmed':
                actions.append('rebind_result')
            if order['kind'] == 'incident':
                actions.append('safety_assistance')
            if not order.get('execution'):
                actions += ['withdraw'] if not order.get('supplier_result') and not linked_entries(order, ledger) else []
                if assessment and current and not expired:
                    actions.append('decide')
                    if approved(order):
                        actions.append('start')
            if approved(order) and order.get('execution'):
                if not order.get('supplier_result'):
                    actions.append('supplier_result')
                if any(Decimal(value) > 0 for group in cash_state(order, ledger)['remaining'].values() for value in group.values()):
                    actions.append('settle')
            if linked_entries(order, ledger):
                actions.append('void_settlement')
    quote = next((q for q in rows(db,'quotes',case.id) if q['status']=='accepted'),None)
    bookings = rows(db,'bookings',case.id)
    eligible = [b['id'] for b in bookings if b['status']=='confirmed' and quote and b['quote_id']==quote['id']
                and ops.trip_matches(b['case_snapshot'],ops.snapshot(case)) and b['kind'] in
                {record(db,'bookings',case.id,bid)['kind'] for bid in order['booking_ids']}]
    problems = blockers(db,case,order,ledger) if not terminal else []
    next_action = None
    if actions and not terminal:
        if order['kind']=='change' and (order.get('supplier_result') or {}).get('outcome')=='confirmed' and not result_current(db,case,order):
            next_action = 'rebind_result' if 'rebind_result' in actions else 'assess'
        elif (order.get('supplier_result') or {}).get('outcome')=='declined' and assessment['revision']<=order['supplier_result'].get('assessment_revision',0):
            next_action='assess'
        elif assessment and assessment.get('amounts') and assessment.get('quote_id') != (quote['id'] if quote else None):
            next_action='assess'
        elif not assessment:
            next_action = 'resolve' if not problems else 'safety_assistance' if order['kind']=='incident' else 'assess'
        elif not order.get('execution'):
            next_action = 'start' if 'start' in actions else 'decide' if 'decide' in actions else 'assess'
        elif 'supplier_result' in actions:
            next_action = 'supplier_result'
        elif 'settle' in actions:
            next_action = 'settle'
        else:
            next_action = 'resolve' if not problems else 'pretrip' if order['kind']=='change' else 'assess'
    return {**order, 'next_action':next_action, 'eligible_result_booking_ids':eligible, 'assessment_current': current, 'assessment_expired': expired,
            'financial_current': financial_current(order,next((q for q in rows(db,'quotes',case.id) if q['status']=='accepted'),None),ledger,rows(db,'service_orders',case.id)), 'cash': cash_state(order, ledger), 'resolution_blockers': problems,
            'actions': actions, 'case_closed': case.status.value == 'closed',
            'settlements': [entry for entry in ledger if entry.get('service_order_id') == order['id']]}


def order_deadlines(db, case):
    if case.status.value=='closed':
        return []
    orders=rows(db,'service_orders',case.id)
    ledger = rows(db, 'ledger', case.id)
    quote = next((q for q in rows(db,'quotes',case.id) if q['status']=='accepted'),None)
    return [ops.deadline_state({'id': o['id'], 'case_id': case.id, 'service_order_id': o['id'],
            'title': o['title'], 'kind': {'incident': 'other'}.get(o['kind'], o['kind']),
            'owner': o['owner'], 'due_at': o['due_at'], 'status': 'open', 'revision': o['revision'],
            'source': 'service_order', 'notes': '緊急，請優先處理' if o['urgency'] == 'urgent' else '改退／旅中工作單',
            'customer_name': case.customer_name, 'case_closed': case.status.value == 'closed', 'history': []})
            for o in orders
            if o['status'] not in TERMINAL or (o['status'] in {'completed', 'supplier_declined'} and not financial_current(o,quote,ledger,orders))]


def mutate(case_id, order_id, data, actor, action, apply):
    def execute(db, case):
        order = record(db, 'service_orders', case_id, order_id)
        ops.require(order['revision'] == data.expected_revision, '工作單已更新，請核對最新內容；本次未儲存')
        ops.require(order['status'] not in TERMINAL or action in TERMINAL_NOTES | {'reopen', 'void_settlement'}, '工作單已結束；可追加聯絡紀錄，其他處理請先重新開單')
        apply(db, case, order)
        order['revision'] += 1
        order['history'].append({'action': action, 'at': now_iso(), **evidence(data, actor),
                                 'data': data.model_dump(mode='json', exclude={'request_id', 'checked', 'expected_revision'})})
        return save(db, 'service_orders', order)
    return command(case_id, data, actor, f'service.{order_id}.{action}', execute)


def create(case_id, data, actor):
    def execute(db, case):
        bookings = [record(db, 'bookings', case_id, bid) for bid in data.booking_ids]
        if data.kind in {'change', 'cancellation'}:
            ops.require(bookings and all(b['status'] == 'confirmed' for b in bookings), '改期／取消須選目前有效的訂購')
        value = new_record(case_id, 'service', {**data.model_dump(mode='json', exclude={'request_id', 'checked'}),
                           'status': 'open', 'target_revisions': {b['id']: b['revision'] for b in bookings},
                           'assessment': None, 'decision': None, 'execution': None, 'supplier_result': None,
                           'history': [{'action': 'create', 'at': now_iso(), **evidence(data, actor)}]})
        return save(db, 'service_orders', value)
    return command(case_id, data, actor, 'service.create', execute)


def patch(case_id, order_id, data, actor):
    def apply(db, case, order):
        changes=data.model_dump(mode='json', include={'owner','due_at','urgency','contact'},exclude_unset=True)
        order['history'].append({'action':'previous_planning','at':now_iso(),'actor':actor,'data':{k:order[k] for k in changes if k!='contact'}})
        order.update(changes)
    return mutate(case_id, order_id, data, actor, 'patch', apply)


def assess(case_id, order_id, data, actor):
    def apply(db, case, order):
        ops.require(data.valid_until > datetime.now(timezone.utc), '供應商條件期限須在未來')
        amounts = [{name: (item.currency if name == 'currency' else f'{getattr(item, name):.2f}')
                    for name in ('currency', *AMOUNT_FIELDS)} for item in data.amounts]
        value = {**data.model_dump(mode='json', exclude={'request_id', 'checked', 'expected_revision', 'amounts'}),
                 'amounts': amounts, 'revision': (order['assessment']['revision'] if order['assessment'] else 0) + 1,
                 'source_state': target_state(db, case, order), 'quote_id': next((q['id'] for q in rows(db,'quotes',case.id) if q['status']=='accepted'),None), **evidence(data, actor)}
        # Supplier facts and linked actual cash are never undone by changed terms.
        order.update(assessment=value, decision=None, execution=None, status='awaiting_customer')
    return mutate(case_id, order_id, data, actor, 'assessment', apply)


def decide(case_id, order_id, data, actor):
    def apply(db, case, order):
        value = order.get('assessment')
        ops.require(not order.get('execution') and value and value['revision'] == data.assessment_revision, '核對方案已更新或已開始處理，請重新查看')
        ops.require(value['source_state'] == target_state(db, case, order) and datetime.fromisoformat(value['valid_until']) > datetime.now(timezone.utc), '條件已過期或案件／訂購已變更，請重新核對方案')
        ops.require(data.occurred_at >= datetime.fromisoformat(value['occurred_at']) - timedelta(minutes=5), '客人決定時間不可早於核對方案')
        if data.decision == 'declined':
            ops.require(not order.get('supplier_result') and not linked_entries(order, rows(db, 'ledger', case.id)), '已有供應商結果或款項，請核對修正方案後完成工作單')
        order.update(decision={**data.model_dump(mode='json', exclude={'request_id', 'checked', 'expected_revision'}), **evidence(data, actor)},
                     status='approved' if data.decision == 'approved' else 'declined')
    return mutate(case_id, order_id, data, actor, 'decision', apply)


def checked_change_bookings(db, case, order, ids, revisions):
    quote = ops.accepted_quote(db, case.id)
    targets = [record(db, 'bookings', case.id, bid) for bid in order['booking_ids']]
    replacements = [record(db, 'bookings', case.id, bid) for bid in ids]
    ops.require(replacements and len(set(ids)) == len(replacements), '請選不重複的實際異動後訂購')
    ops.require(set(revisions) == set(ids), '請核對全部異動後訂購的目前修訂')
    ops.require(all(b['revision'] == revisions[b['id']] for b in replacements), '異動後訂購已更新，請返回最新工作單重新核對；本次未儲存')
    ops.require(all(b['status']=='confirmed' and b['quote_id']==quote['id'] and ops.trip_matches(b['case_snapshot'],ops.snapshot(case)) for b in replacements), '異動後訂購須符合目前採用報價與需求')
    ops.require({b['kind'] for b in targets}<={b['kind'] for b in replacements}, '異動結果未涵蓋原訂購種類')
    ops.require(all(b['status']=='voided' or b['id'] in ids and b['revision']>order['target_revisions'][b['id']] for b in targets), '請先重新核對沿用原訂購，或停用已被替換的原紀錄')
    return replacements


def progress(case_id, order_id, data, actor):
    def apply(db, case, order):
        if data.stage in {'note', 'contact_supplier', 'contact_customer', 'safety_assistance', 'correction'}:
            if data.stage == 'safety_assistance':
                ops.require(order['kind'] == 'incident', '立即協助紀錄只適用旅中事件')
            if data.stage == 'contact_supplier' and not order.get('assessment') and order['status'] not in TERMINAL:
                order['status'] = 'awaiting_supplier'
        elif data.stage == 'withdraw':
            ops.require(not order.get('execution') and not order.get('supplier_result') and not linked_entries(order, rows(db, 'ledger', case.id)), '已處理或有款項，不可當成撤回需求')
            order['status'] = 'withdrawn'
        elif data.stage == 'start':
            value = order.get('assessment')
            ops.require(approved(order) and not order.get('execution'), '請先核對客人採用目前方案，且不可重複開始')
            ops.require(value['source_state'] == target_state(db, case, order) and datetime.fromisoformat(value['valid_until']) > datetime.now(timezone.utc), '條件已過期或資料已變更，請重新核對')
            ops.require(data.occurred_at >= datetime.fromisoformat(order['decision']['occurred_at']) - timedelta(minutes=5), '開始時間不可早於客人採用')
            order['had_delivered_pack'] = order.get('had_delivered_pack', False) or any(p['status'] == 'delivered' for p in rows(db, 'pretrip', case.id))
            order.update(execution={**evidence(data, actor), 'assessment_revision': value['revision']}, status='processing')
        elif data.stage == 'rebind_result':
            ops.require(order['kind']=='change' and (order.get('supplier_result') or {}).get('outcome')=='confirmed', '只有已確認異動結果可以重新核對關聯')
            replacements = checked_change_bookings(db, case, order, data.result_booking_ids, data.booking_revisions)
            order['result_bindings'] = {b['id']:b['revision'] for b in replacements}
        elif data.stage == 'void_settlement':
            entry = record(db, 'ledger', case.id, data.entry_id)
            ops.require(entry.get('service_order_id') == order_id, '收付紀錄不屬於此工作單')
            ops.void_entry(db, case, 'ledger', entry['id'], data, actor, touch_order=False)
        else:
            ops.require(not data.booking_revisions or order['kind'] in {'cancellation', 'change'} and data.outcome=='confirmed', '此結果不適用訂購修訂欄位')
            ops.require(not data.result_booking_ids or order['kind']=='change' and data.outcome=='confirmed', '此結果不適用異動後訂購欄位')
            ops.require(approved(order) and order.get('execution') and not order.get('supplier_result'), '請先開始處理；供應商結果不可覆寫，修正請追加紀錄')
            result = {**evidence(data, actor), 'outcome': data.outcome, 'details': data.details, 'assessment_revision':order['assessment']['revision'], 'result_bookings': {}}
            if data.outcome == 'confirmed' and order['kind'] == 'cancellation':
                ops.require(set(data.booking_revisions) == set(order['booking_ids']), '請核對全部原訂購的目前修訂')
                targets = [record(db, 'bookings', case.id, bid) for bid in order['booking_ids']]
                ops.require(all(b['revision'] == data.booking_revisions[b['id']] for b in targets), '訂購已更新，全部取消紀錄均未儲存')
                for booking in targets:
                    if booking['status'] == 'voided':
                        continue
                    booking.setdefault('history', []).append({'action': 'supplier_cancelled', 'before': {'status': booking['status']}, **evidence(data, actor)})
                    booking.update(status='voided', void_kind='supplier_cancelled', void_reason=data.details,
                                   void_reference=data.reference, void_at=data.occurred_at.isoformat(), void_actor=actor,
                                   cancellation_order_id=order_id, revision=booking['revision']+1)
                    save(db, 'bookings', booking)
                if case.status.value == 'confirmed':
                    quote = next((q for q in rows(db, 'quotes', case.id) if q['status'] == 'accepted'), None)
                    if quote:
                        ops.update_booking_status(db, case, quote)
            elif data.outcome == 'confirmed' and order['kind'] == 'change':
                replacements = checked_change_bookings(db, case, order, data.result_booking_ids, data.booking_revisions)
                result['result_bookings'] = {b['id']: b['revision'] for b in replacements}
            order.update(supplier_result=result, status='settling')
    return mutate(case_id, order_id, data, actor, data.stage, apply)


def settle(case_id, order_id, data, actor):
    def apply(db, case, order):
        ops.require(approved(order) and order.get('execution'), '請先記錄客人採用並開始處理')
        remaining = cash_state(order, rows(db, 'ledger', case.id))['remaining']
        ops.require(data.amount <= Decimal(remaining.get(data.currency, {}).get(data.kind, '0')), '本次金額超過此工作單核對後尚待收退款額')
        quote = next((q for q in rows(db, 'quotes', case.id) if q['status'] == 'accepted'), None)
        ops.record_ledger(db, case, data, actor, quote['id'] if quote else None, order_id)
    return mutate(case_id, order_id, data, actor, 'settlement', apply)


def resolve(case_id, order_id, data, actor):
    def apply(db, case, order):
        ledger = rows(db, 'ledger', case.id)
        problems = blockers(db, case, order, ledger)
        ops.require(not problems, '；'.join(problems))
        if data.end_trip:
            ops.require(order['kind'] in {'cancellation', 'refund'} and (order.get('supplier_result') or {}).get('outcome') == 'confirmed'
                        and not any(b['status'] == 'confirmed' for b in rows(db, 'bookings', case.id)), '旅行取消須有已確認取消／退款結果，且不得仍有有效訂購')
            ops.require(bool(order['assessment']['amounts']), '旅行取消須核對最後應收總額（可為零）')
        quote = next((q for q in rows(db, 'quotes', case.id) if q['status'] == 'accepted'), None)
        order.update(status='supplier_declined' if (order.get('supplier_result') or {}).get('outcome') == 'declined' else 'completed',
                     resolution={**evidence(data, actor), 'summary': data.summary, 'customer_notified_checked': True},
                     end_trip=data.end_trip, balance_quote_id=quote['id'] if quote else None, resolved_at=now_iso())
    return mutate(case_id, order_id, data, actor, 'resolve', apply)


def reopen(case_id, order_id, data, actor):
    def apply(db, case, order):
        ops.require(order['status'] in TERMINAL, '只有已結束工作單可以重新開單')
        order.update(status='open', decision=None, execution=None)
        # Retain immutable supplier_result, all assessment history and real ledger.
    return mutate(case_id, order_id, data, actor, 'reopen', apply)


def receipt(case_id, request_id, actor):
    with connect() as db:
        ops.require(db.execute('SELECT 1 FROM trip_cases WHERE id=?', (case_id,)).fetchone(), '案件不存在')
        found = db.execute('SELECT action,actor,response_json FROM agency_commands WHERE case_id=? AND request_id=?', (case_id, str(request_id))).fetchone()
        if not found:
            return {'committed': False}
        ops.require(found['actor'] == actor and found['action'].startswith('service.'), '重試紀錄不屬於此操作身分或工作單')
        return {'committed': True, 'order_id': json.loads(found['response_json'])['id']}
