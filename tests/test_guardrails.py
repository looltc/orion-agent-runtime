"""Tests for guardrails module (P5)."""

import pytest
from orion_agent_runtime.safety.guardrails import (
    ApprovalAction,
    ApprovalCallback,
    ApprovalResult,
    ApprovalRequired,
    DefaultApprovalCallback,
    GuardrailConfig,
    Guardrails,
    RiskLevel,
    get_guardrails,
    set_guardrails,
)


class MockApprovalCallback(ApprovalCallback):
    """Mock approval callback for testing."""

    def __init__(self, auto_approve=True):
        self.auto_approve = auto_approve
        self.calls = []

    def request_approval(
        self,
        tool_name: str,
        arguments: dict,
        risk_level: RiskLevel,
        context: str = None,
    ) -> ApprovalResult:
        self.calls.append((tool_name, arguments, risk_level, context))

        if self.auto_approve:
            return ApprovalResult(
                action=ApprovalAction.APPROVE,
                approved_by="mock",
            )
        else:
            return ApprovalResult(
                action=ApprovalAction.REJECT,
                reason="Mock rejection",
                approved_by="mock",
            )


class TestGuardrailConfig:
    def test_high_risk_tools(self):
        assert GuardrailConfig.requires_approval("file_write")
        assert GuardrailConfig.requires_approval("execute_command")
        assert GuardrailConfig.requires_approval("database_delete")

    def test_medium_risk_tools(self):
        assert GuardrailConfig.requires_approval("file_create")
        assert GuardrailConfig.requires_approval("database_read")

    def test_low_risk_tools(self):
        assert not GuardrailConfig.requires_approval("math_add")
        assert not GuardrailConfig.requires_approval("text_search")

    def test_risk_levels(self):
        assert GuardrailConfig.get_risk_level("file_write") == RiskLevel.CRITICAL
        assert GuardrailConfig.get_risk_level("execute_command") == RiskLevel.CRITICAL
        assert GuardrailConfig.get_risk_level("file_create") == RiskLevel.MEDIUM
        assert GuardrailConfig.get_risk_level("math_add") == RiskLevel.LOW


class TestApprovalResult:
    def test_creation(self):
        result = ApprovalResult(
            action=ApprovalAction.APPROVE,
            reason="Test reason",
            approved_by="tester",
        )
        assert result.action == ApprovalAction.APPROVE
        assert result.reason == "Test reason"
        assert result.approved_by == "tester"


class TestGuardrails:
    def test_low_risk_auto_approve(self):
        guardrails = Guardrails(MockApprovalCallback())
        result = guardrails.check_before_execution(
            tool_name="math_add",
            arguments={"a": 1, "b": 2},
            context="test",
        )
        assert result.action == ApprovalAction.APPROVE
        assert len(guardrails.get_approval_history()) == 1

    def test_high_risk_requires_approval(self):
        callback = MockApprovalCallback(auto_approve=True)
        guardrails = Guardrails(callback)
        result = guardrails.check_before_execution(
            tool_name="file_write",
            arguments={"path": "/tmp/test", "content": "data"},
            context="test",
        )
        assert result.action == ApprovalAction.APPROVE
        assert result.approved_by == "mock"
        assert len(callback.calls) == 1
        assert callback.calls[0][0] == "file_write"

    def test_approval_rejection_raises_exception(self):
        callback = MockApprovalCallback(auto_approve=False)
        guardrails = Guardrails(callback)

        with pytest.raises(ApprovalRequired) as exc_info:
            guardrails.check_before_execution(
                tool_name="file_delete",
                arguments={"path": "/tmp/test"},
                context="test",
            )

        assert "not approved" in str(exc_info.value)

    def test_approval_history(self):
        guardrails = Guardrails(MockApprovalCallback())
        guardrails.check_before_execution("math_add", {"a": 1}, "test")
        guardrails.check_before_execution("file_write", {"path": "/tmp"}, "test")

        history = guardrails.get_approval_history()
        assert len(history) == 2
        assert history[0]["tool_name"] == "math_add"
        assert history[1]["tool_name"] == "file_write"
        assert history[1]["requires_approval"] is True

    def test_clear_history(self):
        guardrails = Guardrails(MockApprovalCallback())
        guardrails.check_before_execution("math_add", {"a": 1}, "test")
        assert len(guardrails.get_approval_history()) == 1

        guardrails.clear_history()
        assert len(guardrails.get_approval_history()) == 0


class TestGlobalGuardrails:
    def test_get_guardrails_singleton(self):
        g1 = get_guardrails()
        g2 = get_guardrails()
        assert g1 is g2

    def test_set_guardrails(self):
        new_guardrails = Guardrails(MockApprovalCallback())
        set_guardrails(new_guardrails)

        g = get_guardrails()
        assert g is new_guardrails

        # Reset to default
        set_guardrails(Guardrails())


class TestDefaultApprovalCallback:
    def test_auto_approve_mode(self):
        import os
        from orion_agent_runtime.safety.guardrails import GuardrailConfig

        # Test with auto-approve environment variable
        original = os.environ.get("ORION_AUTO_APPROVE")

        # 启用自动批准并重载配置
        os.environ["ORION_AUTO_APPROVE"] = "true"
        GuardrailConfig.get_auto_approve(reload=True)

        callback = DefaultApprovalCallback()
        result = callback.request_approval(
            tool_name="file_write",
            arguments={"path": "/tmp/test"},
            risk_level=RiskLevel.CRITICAL,
            context="test",
        )
        assert result.action == ApprovalAction.APPROVE
        assert result.approved_by == "system"

        # Restore original and reload configuration
        if original is None:
            os.environ.pop("ORION_AUTO_APPROVE", None)
        else:
            os.environ["ORION_AUTO_APPROVE"] = original
        GuardrailConfig.get_auto_approve(reload=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])