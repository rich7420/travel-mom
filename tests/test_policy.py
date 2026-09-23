from app.models import ActionType
from app.services.policy import policy


def test_payment_blocked():
    d = policy.decide(ActionType.PAYMENT)
    assert not d.allowed
    assert d.level == 'blocked'


def test_booking_needs_strong_confirmation():
    d = policy.decide(ActionType.BOOK)
    assert d.allowed and d.requires_approval and d.level == 'strong-confirm'
