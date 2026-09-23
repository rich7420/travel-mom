from __future__ import annotations

from dataclasses import dataclass

from app.models import ActionType


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    level: str
    reason: str


class ActionPolicy:
    """Hard application-layer guardrail. Prompt instructions are not trusted as authorization."""

    def decide(self, action: ActionType) -> PolicyDecision:
        if action in {ActionType.READ, ActionType.DRAFT}:
            return PolicyDecision(True, False, "automatic", "Read-only or draft action")
        if action == ActionType.ACCEPT_PRICE_CHANGE:
            return PolicyDecision(True, True, "confirm", "Changed live price must be explicitly accepted before checkout")
        if action == ActionType.SEND_MESSAGE:
            return PolicyDecision(True, True, "confirm", "External communication must be previewed and confirmed")
        if action in {ActionType.BOOK, ActionType.TICKET, ActionType.CANCEL, ActionType.REFUND}:
            return PolicyDecision(True, True, "strong-confirm", "Irreversible travel action requires explicit human approval")
        if action == ActionType.PAYMENT:
            return PolicyDecision(False, True, "blocked", "POC never handles card data or presses final payment")
        return PolicyDecision(False, True, "blocked", "Unknown action")


policy = ActionPolicy()
