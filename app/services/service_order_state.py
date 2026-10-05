"""Pure cash and source-binding rules shared by commands and case summaries."""
from decimal import Decimal

TERMINAL = {'completed', 'declined', 'withdrawn', 'supplier_declined'}
CASH_KINDS = ('customer_receipt', 'customer_refund', 'supplier_payment', 'supplier_refund')

def ledger_totals(entries: list[dict]) -> dict:
    totals = {}
    for entry in entries:
        if entry.get("status") == "voided":
            continue
        group = totals.setdefault(entry["currency"], {kind: Decimal(0) for kind in ["customer_receipt", "customer_refund", "supplier_payment", "supplier_refund"]})
        group[entry["kind"]] += Decimal(entry["amount"])
    return totals


def linked_entries(order, ledger):
    return [item for item in ledger if item.get('service_order_id') == order['id'] and item['status'] != 'voided']


def cash_state(order, ledger):
    actual = ledger_totals(linked_entries(order, ledger))
    plan = {item['currency']: item for item in (order.get('assessment') or {}).get('amounts', [])}
    currencies = set(plan) | set(actual)
    remaining, current = {}, True
    for currency in sorted(currencies):
        remaining[currency] = {}
        for kind in CASH_KINDS:
            delta = Decimal(plan.get(currency, {}).get(kind, '0')) - actual.get(currency, {}).get(kind, Decimal(0))
            remaining[currency][kind] = f'{delta:.2f}'
            current = current and delta == 0
    return {'actual': {c: {k: f'{v:.2f}' for k, v in group.items()} for c, group in actual.items()},
            'remaining': remaining, 'current': current}


def trip_pending(order, quote=None, bookings=()):
    # No key for an empty set, so existing schema-805 delivered hashes survive.
    if order['kind'] not in {'change', 'cancellation'} or order['status'] in TERMINAL:
        return False
    result = order.get('supplier_result')
    if not result:
        return True
    if result['outcome'] == 'declined':
        return False
    if order['kind'] == 'cancellation':
        return any(b['status'] != 'voided' for b in bookings if b['id'] in order['booking_ids'])
    current = {b['id']: b for b in bookings}
    return not quote or not order.get('result_bindings', result['result_bookings']) or any(
        bid not in current or current[bid]['revision'] != revision
        or current[bid]['status'] != 'confirmed' or current[bid]['quote_id'] != quote['id']
        for bid, revision in order.get('result_bindings', result['result_bookings']).items())


def final_dues(quote, ledger, orders):
    due = dict(quote['totals'] if quote else {})
    for order in sorted(orders, key=lambda item: (item.get('resolved_at', ''), item['id'])):
        if order['status'] not in {'completed', 'supplier_declined'} or not cash_state(order, ledger)['current']:
            continue
        if order.get('balance_quote_id') != (quote['id'] if quote else None) and not (not quote and order.get('end_trip')):
            continue
        for item in (order.get('assessment') or {}).get('amounts', []):
            due[item['currency']] = item['final_customer_due']
    return due


def ended_trip(quote, bookings, orders, ledger):
    return not any(b['status'] == 'confirmed' for b in bookings) and any(
        o['status'] == 'completed' and o.get('end_trip') and cash_state(o, ledger)['current']
        and (not quote or o.get('balance_quote_id') == quote['id']) for o in orders)



def financial_current(order, quote, ledger, orders=()):
    if not cash_state(order, ledger)['current']:
        return False
    if not quote or not (order.get('assessment') or {}).get('amounts'):
        # Withdrawing adoption at business closure never undoes settled cash.
        return True
    resolved = [o for o in orders if o['status'] in {'completed','supplier_declined'}
                and (o.get('assessment') or {}).get('amounts')]
    latest = max(resolved,key=lambda o:(o.get('resolved_at',''),o['id']),default=order)
    # A newer resolved whole-case assessment supersedes historical quote binding.
    return latest['id'] != order['id'] or order.get('balance_quote_id') == quote['id']
