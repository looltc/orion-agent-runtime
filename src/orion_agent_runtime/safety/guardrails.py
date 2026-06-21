"""Human approval guardrails for dangerous operations (P5).

Provides approval hooks for high-risk tools (write, execute, delete, etc.)
to ensure human oversight before irreversible actions.
"""

from enum import Enum
from typing import Callable, Dict, Optional, Set
import os


class RiskLevel(Enum):
    """Risk levels for tool operations."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalAction(Enum):
    """Approval decision."""
    APPROVE = "approve"
    REJECT = "reject"
    ABORT = "abort"


class ApprovalRequired(Exception):
    """Raised when human approval is required for an operation."""
    pass


class ApprovalResult:
    """Result of an approval request."""
    def __init__(self, action: ApprovalAction, reason: str = "", approved_by: str = "system"):
        self.action = action
        self.reason = reason
        self.approved_by = approved_by


class GuardrailConfig:
    """Configuration for guardrails behavior."""

    # Tools that require approval
    HIGH_RISK_TOOLS: Set[str] = {
        "file_write",
        "file_delete",
        "file_rename",
        "execute_command",
        "execute_script",
        "database_write",
        "database_delete",
        "api_post",
        "api_delete",
        "api_put",
    }

    MEDIUM_RISK_TOOLS: Set[str] = {
        "file_create",
        "database_read",
        "api_get",
        "network_scan",
    }

    # Lazy-loaded configuration (similar to config.py)
    _auto_approve: Optional[bool] = None
    _approval_timeout: Optional[int] = None

    @classmethod
    def get_auto_approve(cls, reload: bool = False) -> bool:
        """Get auto-approve setting (lazy-loaded, can be reloaded)."""
        if cls._auto_approve is None or reload:
            cls._auto_approve = os.getenv("ORION_AUTO_APPROVE", "false").lower() == "true"
        return cls._auto_approve

    @classmethod
    def get_approval_timeout(cls, reload: bool = False) -> int:
        """Get approval timeout (lazy-loaded, can be reloaded)."""
        if cls._approval_timeout is None or reload:
            cls._approval_timeout = int(os.getenv("ORION_APPROVAL_TIMEOUT", "300"))
        return cls._approval_timeout

    @classmethod
    def get_risk_level(cls, tool_name: str) -> RiskLevel:
        """Get risk level for a tool."""
        if tool_name in cls.HIGH_RISK_TOOLS:
            return RiskLevel.CRITICAL
        if tool_name in cls.MEDIUM_RISK_TOOLS:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @classmethod
    def requires_approval(cls, tool_name: str) -> bool:
        """Check if a tool requires approval."""
        return cls.get_risk_level(tool_name) in (RiskLevel.MEDIUM, RiskLevel.CRITICAL)


class ApprovalCallback:
    """Callback interface for human approval."""

    def request_approval(
        self,
        tool_name: str,
        arguments: Dict,
        risk_level: RiskLevel,
        context: Optional[str] = None,
    ) -> ApprovalResult:
        """Request human approval for an operation.

        Args:
            tool_name: The tool being called
            arguments: The arguments to the tool
            risk_level: The risk level of the operation
            context: Additional context (run_id, user_input, etc.)

        Returns:
            ApprovalResult with the decision
        """
        raise NotImplementedError("Subclasses must implement request_approval")


class DefaultApprovalCallback(ApprovalCallback):
    """Default approval callback using stdin for interactive approval."""

    def request_approval(
        self,
        tool_name: str,
        arguments: Dict,
        risk_level: RiskLevel,
        context: Optional[str] = None,
    ) -> ApprovalResult:
        """Request approval via stdin."""
        if GuardrailConfig.get_auto_approve():
            return ApprovalResult(
                action=ApprovalAction.APPROVE,
                reason="Auto-approved (ORION_AUTO_APPROVE=true)",
                approved_by="system",
            )

        risk_emoji = {
            RiskLevel.LOW: "🟢",
            RiskLevel.MEDIUM: "🟡",
            RiskLevel.HIGH: "🟠",
            RiskLevel.CRITICAL: "🔴",
        }

        print(f"\n{'='*60}")
        print(f"{risk_emoji[risk_level]} APPROVAL REQUIRED - {risk_level.value.upper()}")
        print(f"{'='*60}")
        print(f"Tool: {tool_name}")
        print(f"Risk: {risk_level.value}")
        if context:
            print(f"Context: {context}")
        print(f"\nArguments:")
        for k, v in arguments.items():
            print(f"  {k}: {v}")
        print(f"{'='*60}")

        while True:
            response = input("\nApprove this operation? [y(es)/n(o)/a(bort)]: ").strip().lower()
            if response in ("y", "yes"):
                return ApprovalResult(
                    action=ApprovalAction.APPROVE,
                    approved_by="human",
                )
            elif response in ("n", "no"):
                return ApprovalResult(
                    action=ApprovalAction.REJECT,
                    approved_by="human",
                )
            elif response in ("a", "abort"):
                return ApprovalResult(
                    action=ApprovalAction.ABORT,
                    reason="Operation aborted by human",
                    approved_by="human",
                )
            else:
                print("Invalid response. Please enter 'y', 'n', or 'a'.")


class Guardrails:
    """Main guardrails class for enforcing safety policies."""

    def __init__(self, approval_callback: Optional[ApprovalCallback] = None):
        """Initialize guardrails with an approval callback."""
        self.approval_callback = approval_callback or DefaultApprovalCallback()
        self._approval_history: list = []

    def check_before_execution(
        self,
        tool_name: str,
        arguments: Dict,
        context: Optional[str] = None,
    ) -> ApprovalResult:
        """Check if an operation requires approval before execution.

        Args:
            tool_name: The tool being called
            arguments: The arguments to the tool
            context: Additional context (run_id, user_input, etc.)

        Returns:
            ApprovalResult with the decision

        Raises:
            ApprovalRequired: When approval is required and not granted
        """
        risk_level = GuardrailConfig.get_risk_level(tool_name)

        # Log the check
        self._approval_history.append({
            "tool_name": tool_name,
            "risk_level": risk_level.value,
            "requires_approval": GuardrailConfig.requires_approval(tool_name),
            "context": context,
        })

        if not GuardrailConfig.requires_approval(tool_name):
            return ApprovalResult(
                action=ApprovalAction.APPROVE,
                reason=f"Low risk tool ({risk_level.value})",
                approved_by="system",
            )

        # Request approval
        result = self.approval_callback.request_approval(
            tool_name=tool_name,
            arguments=arguments,
            risk_level=risk_level,
            context=context,
        )

        self._approval_history[-1]["result"] = result.action.value
        self._approval_history[-1]["approved_by"] = result.approved_by

        if result.action != ApprovalAction.APPROVE:
            raise ApprovalRequired(
                f"Operation '{tool_name}' not approved: {result.action.value}"
            )

        return result

    def get_approval_history(self) -> list:
        """Get the history of approval checks."""
        return self._approval_history.copy()

    def clear_history(self) -> None:
        """Clear the approval history."""
        self._approval_history.clear()


# Global guardrails instance
_global_guardrails: Optional[Guardrails] = None


def get_guardrails() -> Guardrails:
    """Get the global guardrails instance."""
    global _global_guardrails
    if _global_guardrails is None:
        _global_guardrails = Guardrails()
    return _global_guardrails


def set_guardrails(guardrails: Guardrails) -> None:
    """Set the global guardrails instance."""
    global _global_guardrails
    _global_guardrails = guardrails