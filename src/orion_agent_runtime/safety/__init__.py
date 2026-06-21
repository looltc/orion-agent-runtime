"""Safety module for guardrails and human approval hooks (P5)."""

from orion_agent_runtime.safety.guardrails import (
    ApprovalAction,
    ApprovalCallback,
    ApprovalRequired,
    ApprovalResult,
    DefaultApprovalCallback,
    GuardrailConfig,
    Guardrails,
    RiskLevel,
    get_guardrails,
    set_guardrails,
)

__all__ = [
    "ApprovalAction",
    "ApprovalCallback",
    "ApprovalRequired",
    "ApprovalResult",
    "DefaultApprovalCallback",
    "GuardrailConfig",
    "Guardrails",
    "RiskLevel",
    "get_guardrails",
    "set_guardrails",
]