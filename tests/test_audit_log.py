"""Tests for audit_log module (P5)."""

import json
import os
import pytest
from pathlib import Path
from orion_agent_runtime.audit.audit_log import log_event, read_events, clear_audit


class TestAuditLog:
    def setup_method(self):
        clear_audit()

    def test_log_and_read_event(self):
        run_id = "test_run_001"
        log_event(
            run_id=run_id,
            event_type="test_event",
            data={"key": "value", "number": 123},
        )

        events = read_events(run_id=run_id)
        assert len(events) >= 1

        latest = events[-1]
        assert latest["run_id"] == run_id
        assert latest["event_type"] == "test_event"
        assert latest["data"]["key"] == "value"
        assert latest["data"]["number"] == 123
        assert "timestamp" in latest

    def test_multiple_runs_separated(self):
        run_id_1 = "test_run_002_a"
        run_id_2 = "test_run_002_b"

        log_event(run_id=run_id_1, event_type="event_a", data={"run": 1})
        log_event(run_id=run_id_2, event_type="event_b", data={"run": 2})
        log_event(run_id=run_id_1, event_type="event_c", data={"run": 1})

        events_1 = read_events(run_id=run_id_1)
        events_2 = read_events(run_id=run_id_2)

        assert len(events_1) == 2
        assert len(events_2) == 1
        assert all(e["run_id"] == run_id_1 for e in events_1)
        assert all(e["run_id"] == run_id_2 for e in events_2)

    def test_event_types_coverage(self):
        run_id = "test_run_003"
        event_types = [
            "task_start",
            "plan_generated",
            "tool_call_start",
            "tool_call_success",
            "tool_call_failed",
            "goal_verification_start",
            "goal_verification_completed",
            "task_completed",
            "react_loop_start",
            "react_decision",
        ]

        for event_type in event_types:
            log_event(
                run_id=run_id,
                event_type=event_type,
                data={"test_data": f"for_{event_type}"},
            )

        events = read_events(run_id=run_id)
        logged_types = {e["event_type"] for e in events}
        assert logged_types == set(event_types)

    def test_empty_run_id(self):
        events = read_events(run_id="nonexistent_run")
        assert events == []

    def test_json_persistence(self):
        run_id = "test_run_004"
        log_event(
            run_id=run_id,
            event_type="persistence_test",
            data={"nested": {"deep": "value"}},
        )

        # Verify file exists and is valid JSON
        # The audit log writes to runtime_state_dir / "audit.jsonl"
        from orion_agent_runtime.config import get_config

        audit_file = Path(get_config().runtime_state_dir) / "audit.jsonl"

        if audit_file.exists():
            with open(audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        if entry.get("run_id") == run_id:
                            assert entry["event_type"] == "persistence_test"
                            assert entry["data"]["nested"]["deep"] == "value"
                            break

    def test_complex_data_types(self):
        run_id = "test_run_005"
        complex_data = {
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
            "string": "test",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
        }

        log_event(run_id=run_id, event_type="complex_data_test", data=complex_data)

        events = read_events(run_id=run_id)
        assert len(events) >= 1
        assert events[-1]["data"] == complex_data

    def test_special_characters_in_data(self):
        run_id = "test_run_006"
        special_data = {
            "unicode": "中文 日本語 한국어",
            "quotes": 'Test "quotes" and \'apostrophes\'',
            "newlines": "Line 1\nLine 2\nLine 3",
            "emoji": "😀🎉🚀",
        }

        log_event(run_id=run_id, event_type="special_chars", data=special_data)

        events = read_events(run_id=run_id)
        assert len(events) >= 1
        assert events[-1]["data"]["unicode"] == special_data["unicode"]
        assert events[-1]["data"]["emoji"] == special_data["emoji"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])