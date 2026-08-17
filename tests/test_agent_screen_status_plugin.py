from __future__ import annotations

import importlib.util
import pathlib
import re
import threading
import unittest
from types import ModuleType
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "integrations/hermes/agent-screen-status"
PLUGIN = PLUGIN_DIR / "__init__.py"


def load_plugin() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agent_screen_status_integration", PLUGIN)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load plugin from {PLUGIN}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentScreenStatusIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.module: Any = load_plugin()
        self.module._ACTIVE_TURNS.clear()
        if hasattr(self.module, "_SPECIALIST_ACTIVE_TURNS"):
            for turns in self.module._SPECIALIST_ACTIVE_TURNS.values():
                turns.clear()
        if hasattr(self.module, "_SPECIALIST_TURN_SCREENS"):
            self.module._SPECIALIST_TURN_SCREENS.clear()
        if hasattr(self.module, "_SPECIALIST_ERRORS"):
            self.module._SPECIALIST_ERRORS.clear()
        if hasattr(self.module, "_SPECIALIST_LATCHED_ERRORS"):
            self.module._SPECIALIST_LATCHED_ERRORS.clear()
        self.events = []
        self.specialist_events = []
        self.original_publish = self.module._publish
        self.module._publish = lambda state, task: self.events.append((state, task))
        self.original_publish_specialist = getattr(
            self.module, "_publish_specialist", None
        )
        if self.original_publish_specialist is not None:
            self.module._publish_specialist = (
                lambda screen, state, task: self.specialist_events.append(
                    (screen, state, task)
                )
            )

    def tearDown(self):
        self.module._publish = self.original_publish
        if self.original_publish_specialist is not None:
            self.module._publish_specialist = self.original_publish_specialist
        self.module._ACTIVE_TURNS.clear()
        if hasattr(self.module, "_SPECIALIST_ACTIVE_TURNS"):
            for turns in self.module._SPECIALIST_ACTIVE_TURNS.values():
                turns.clear()
        if hasattr(self.module, "_SPECIALIST_TURN_SCREENS"):
            self.module._SPECIALIST_TURN_SCREENS.clear()
        if hasattr(self.module, "_SPECIALIST_ERRORS"):
            self.module._SPECIALIST_ERRORS.clear()
        if hasattr(self.module, "_SPECIALIST_LATCHED_ERRORS"):
            self.module._SPECIALIST_LATCHED_ERRORS.clear()

    def test_integration_is_complete_and_sanitized(self):
        paths = [
            PLUGIN,
            PLUGIN_DIR / "plugin.yaml",
            PLUGIN_DIR / "install.sh",
            PLUGIN_DIR / "README.md",
        ]
        for path in paths:
            self.assertTrue(path.is_file(), str(path))
        combined = "\n".join(path.read_text() for path in paths)
        installer = (PLUGIN_DIR / "install.sh").read_text()
        docs = (PLUGIN_DIR / "README.md").read_text()
        self.assertIn("AGENT_SCREEN_STATUS_PUBLISHER", combined)
        self.assertIn("AGENT_SCREEN_STATUS_PUBLISHER_2", combined)
        self.assertIn("AGENT_SCREEN_STATUS_PUBLISHER_3", combined)
        self.assertIn("AGENT_SCREEN_STATUS_PUBLISHER_4", combined)
        self.assertIn('command -v hermes', installer)
        self.assertIn("systemctl --user edit hermes-gateway.service", docs)
        for forbidden in ("/root/", "id_ed25519"):
            self.assertNotIn(forbidden, combined)
        ipv4_addresses = set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", combined))
        documentation_prefixes = ("127.0.0.1", "192.0.2.", "198.51.100.", "203.0.113.")
        self.assertTrue(
            all(address.startswith(documentation_prefixes) for address in ipv4_addresses),
            f"non-documentation IP address found: {sorted(ipv4_addresses)}",
        )

    def test_turn_transitions_working_to_idle(self):
        kwargs = {
            "platform": "telegram", "turn_id": "t1",
            "user_message": "run speedtest",
        }
        self.module._pre_llm_call(**kwargs)
        self.module._post_llm_call(**kwargs)
        self.assertEqual(self.events, [("working", "Running network speed test")])
        self.module._on_session_end(**kwargs, completed=True, failed=False)
        self.assertEqual(self.events, [
            ("working", "Running network speed test"),
            ("idle", "Ready to coordinate operations"),
        ])

    def test_raw_prompt_is_not_published(self):
        self.module._pre_llm_call(
            platform="telegram", turn_id="t1",
            user_message="Customer Alice phone 0123456789",
        )
        self.assertEqual(self.events, [("working", "Handling owner request")])

    def test_overlapping_top_level_turns_do_not_idle_early(self):
        self.module._pre_llm_call(platform="telegram", turn_id="t1")
        self.module._pre_llm_call(platform="telegram", turn_id="t2")
        self.module._on_session_end(
            platform="telegram", turn_id="t1", completed=True, failed=False
        )
        self.assertEqual(self.events[-1], ("working", "Handling owner request"))
        self.module._on_session_end(
            platform="telegram", turn_id="t2", completed=True, failed=False
        )
        self.assertEqual(self.events[-1], ("idle", "Ready to coordinate operations"))

    def test_concurrent_new_turn_cannot_be_overwritten_by_stale_idle(self):
        idle_publish_started = threading.Event()
        release_idle_publish = threading.Event()

        def blocking_publish(state, task):
            if state == "idle":
                idle_publish_started.set()
                release_idle_publish.wait(timeout=2)
            self.events.append((state, task))

        self.module._publish = blocking_publish
        self.module._pre_llm_call(platform="telegram", turn_id="t1")
        self.events.clear()

        finish = threading.Thread(
            target=self.module._on_session_end,
            kwargs={
                "platform": "telegram", "turn_id": "t1",
                "completed": True, "failed": False,
            },
        )
        finish.start()
        self.assertTrue(idle_publish_started.wait(timeout=1))

        start = threading.Thread(
            target=self.module._pre_llm_call,
            kwargs={"platform": "telegram", "turn_id": "t2"},
        )
        start.start()
        start.join(timeout=0.2)
        release_idle_publish.set()
        finish.join(timeout=1)
        start.join(timeout=1)

        self.assertFalse(finish.is_alive())
        self.assertFalse(start.is_alive())
        self.assertEqual(self.events[-1], ("working", "Handling owner request"))
        self.assertEqual(self.module._ACTIVE_TURNS, {"t2"})

    def test_background_review_fork_is_ignored(self):
        self.module._pre_llm_call(
            platform="telegram", turn_id="review-1",
            parent_session_id="parent-session",
            user_message="Review conversation with smart home history",
        )
        self.assertEqual(self.events, [])
        self.assertEqual(self.module._ACTIVE_TURNS, set())

    def test_background_review_post_without_parent_is_ignored_when_untracked(self):
        self.module._pre_llm_call(
            platform="telegram", turn_id="review-1",
            parent_session_id="parent-session",
        )
        self.module._post_llm_call(platform="telegram", turn_id="review-1")
        self.assertEqual(self.events, [])
        self.assertEqual(self.module._ACTIVE_TURNS, set())

    def test_background_fork_does_not_hold_foreground_working(self):
        foreground = {"platform": "telegram", "turn_id": "t1"}
        self.module._pre_llm_call(**foreground)
        self.module._pre_llm_call(
            platform="telegram", turn_id="review-1",
            parent_session_id="parent-session",
        )
        self.module._on_session_end(**foreground, completed=True, failed=False)
        self.assertEqual(self.events[-1], ("idle", "Ready to coordinate operations"))
        self.assertEqual(self.module._ACTIVE_TURNS, set())

    def test_interrupted_turn_becomes_attention(self):
        self.module._pre_llm_call(platform="telegram", turn_id="t1")
        self.module._on_session_end(
            platform="telegram", turn_id="t1", completed=False, interrupted=True,
        )
        self.assertEqual(
            self.events[-1], ("error", "Turn interrupted — ready for review")
        )

    def test_failed_turn_becomes_attention(self):
        self.module._pre_llm_call(platform="telegram", turn_id="t1")
        self.module._on_session_end(
            platform="telegram", turn_id="t1",
            completed=False, failed=True, interrupted=False,
        )
        self.assertEqual(
            self.events[-1], ("error", "Turn failed — ready for review")
        )

    def test_approval_hooks_use_real_gateway_surface_for_scope(self):
        self.module._pre_llm_call(platform="telegram", turn_id="t1")
        self.module._pre_approval_request(surface="gateway", turn_id="t1")
        self.module._post_approval_response(
            surface="gateway", turn_id="t1", choice="once"
        )
        self.assertEqual(self.events[-2:], [
            ("waiting_approval", "Waiting for owner approval"),
            ("working", "Continuing approved task"),
        ])

    def test_untracked_approval_turn_is_ignored(self):
        self.module._pre_llm_call(platform="telegram", turn_id="foreground")
        self.events.clear()
        self.module._pre_approval_request(
            surface="gateway", turn_id="untracked-background"
        )
        self.module._post_approval_response(
            surface="gateway", turn_id="untracked-background", choice="deny"
        )
        self.assertEqual(self.events, [])

    def test_smart_deny_is_attention_not_continuation(self):
        self.module._pre_llm_call(platform="telegram", turn_id="t1")
        self.module._post_approval_response(
            surface="smart", turn_id="t1", choice="smart_deny"
        )
        self.assertEqual(
            self.events[-1], ("error", "Approval not granted — ready for review")
        )

    def test_notify_failed_is_attention_not_continuation(self):
        self.module._pre_llm_call(platform="telegram", turn_id="t1")
        self.module._post_approval_response(
            surface="gateway", turn_id="t1", choice="notify_failed"
        )
        self.assertEqual(
            self.events[-1], ("error", "Approval notification failed — ready for review")
        )

    def test_smart_approve_continues_tracked_turn(self):
        self.module._pre_llm_call(platform="telegram", turn_id="t1")
        self.module._post_approval_response(
            surface="smart", turn_id="t1", choice="smart_approve"
        )
        self.assertEqual(self.events[-1], ("working", "Continuing approved task"))

    def test_cli_timeout_is_attention(self):
        self.module._pre_llm_call(platform="cli", turn_id="t1")
        self.module._post_approval_response(
            surface="cli", turn_id="t1", choice="timeout"
        )
        self.assertEqual(
            self.events[-1], ("error", "Approval not granted — ready for review")
        )

    def test_unknown_approval_outcome_fails_closed(self):
        self.module._pre_llm_call(platform="telegram", turn_id="t1")
        self.module._post_approval_response(
            surface="gateway", turn_id="t1", choice="unexpected"
        )
        self.assertEqual(
            self.events[-1], ("error", "Unknown approval outcome — ready for review")
        )

    def test_denial_error_survives_post_llm_until_session_end(self):
        turn = {"platform": "telegram", "turn_id": "t1"}
        self.module._pre_llm_call(**turn)
        self.module._post_approval_response(
            surface="gateway", turn_id="t1", choice="deny"
        )
        self.module._post_llm_call(**turn)
        self.assertEqual(
            self.events[-1], ("error", "Approval not granted — ready for review")
        )
        self.module._on_session_end(**turn, completed=True, failed=False)
        self.assertEqual(
            self.events[-1], ("error", "Approval not granted — ready for review")
        )

    def test_transport_surface_wait_and_approve_lifecycle(self):
        turn = {"platform": "telegram", "turn_id": "t1"}
        self.module._pre_llm_call(**turn)
        self.module._pre_approval_request(surface="transport:slack", turn_id="t1")
        self.module._post_approval_response(
            surface="transport:slack", turn_id="t1", choice="once"
        )
        self.module._on_session_end(**turn, completed=True, failed=False)
        self.assertEqual(self.events[-3:], [
            ("waiting_approval", "Waiting for owner approval"),
            ("working", "Continuing approved task"),
            ("idle", "Ready to coordinate operations"),
        ])

    def test_transport_failure_is_attention_through_session_end(self):
        turn = {"platform": "telegram", "turn_id": "t1"}
        self.module._pre_llm_call(**turn)
        self.module._post_approval_response(
            surface="transport:slack", turn_id="t1", choice="transport_timeout"
        )
        self.module._post_llm_call(**turn)
        self.module._on_session_end(**turn, completed=True, failed=False)
        self.assertEqual(
            self.events[-1], ("error", "Approval transport failed — ready for review")
        )

    def test_denial_cannot_be_erased_by_later_approval(self):
        turn = {"platform": "telegram", "turn_id": "t1"}
        self.module._pre_llm_call(**turn)
        self.module._post_approval_response(
            surface="gateway", turn_id="t1", choice="deny"
        )
        self.module._post_approval_response(
            surface="gateway", turn_id="t1", choice="once"
        )
        self.assertEqual(
            self.events[-1], ("error", "Approval not granted — ready for review")
        )
        self.module._on_session_end(**turn, completed=True, failed=False)
        self.assertEqual(
            self.events[-1], ("error", "Approval not granted — ready for review")
        )

    def test_overlapping_turn_error_is_latched_until_all_turns_end(self):
        first = {"platform": "telegram", "turn_id": "t1"}
        second = {"platform": "telegram", "turn_id": "t2"}
        self.module._pre_llm_call(**first)
        self.module._pre_llm_call(**second)
        self.module._post_approval_response(
            surface="transport:slack", turn_id="t1", choice="transport_timeout"
        )
        self.module._on_session_end(**first, completed=True, failed=False)
        self.assertEqual(
            self.events[-1], ("error", "Approval transport failed — ready for review")
        )
        self.module._pre_approval_request(
            surface="transport:slack", turn_id="t2"
        )
        self.assertEqual(
            self.events[-1], ("error", "Approval transport failed — ready for review")
        )
        self.module._post_approval_response(
            surface="transport:slack", turn_id="t2", choice="once"
        )
        self.assertEqual(
            self.events[-1], ("error", "Approval transport failed — ready for review")
        )
        self.module._on_session_end(**second, completed=True, failed=False)
        self.assertEqual(
            self.events[-1], ("error", "Approval transport failed — ready for review")
        )

    def test_repeated_pre_llm_cannot_clear_latched_error(self):
        turn = {"platform": "telegram", "turn_id": "t1"}
        self.module._pre_llm_call(**turn)
        self.module._post_approval_response(
            surface="gateway", turn_id="t1", choice="deny"
        )
        self.module._pre_llm_call(**turn)
        self.assertEqual(
            self.events[-1], ("error", "Approval not granted — ready for review")
        )

    def test_screen_two_tool_lifecycle_stays_working_until_session_end(self):
        turn = {"platform": "telegram", "turn_id": "t1"}
        self.module._pre_llm_call(**turn)
        self.module._pre_tool_call(
            tool_name="mcp__cua_screen2__get_browser_state", turn_id="t1"
        )
        self.module._post_tool_call(
            tool_name="mcp__cua_screen2__get_browser_state",
            turn_id="t1", status="ok",
        )
        self.assertEqual(self.specialist_events, [
            (2, "working", "Reviewing recruitment workspace")
        ])
        self.module._on_session_end(**turn, completed=True, failed=False)
        self.assertEqual(self.specialist_events[-1], (
            2, "idle", "Ready for recruitment review"
        ))

    def test_screen_three_and_four_tools_map_to_correct_specialists(self):
        turn = {"platform": "telegram", "turn_id": "t1"}
        self.module._pre_llm_call(**turn)
        self.module._pre_tool_call(
            tool_name="mcp__cua_screen3__get_browser_state", turn_id="t1"
        )
        self.module._pre_tool_call(
            tool_name="mcp__cua_screen4__capture", turn_id="t1"
        )
        self.assertEqual(self.specialist_events, [
            (3, "working", "Working in GBAsset workspace"),
            (4, "working", "Working on product design"),
        ])
        self.module._on_session_end(**turn, completed=True, failed=False)
        self.assertEqual(self.specialist_events[-2:], [
            (3, "idle", "Ready for GBAsset work"),
            (4, "idle", "Ready for product design work"),
        ])

    def test_untracked_and_screen_one_tools_do_not_publish_specialists(self):
        self.module._pre_tool_call(
            tool_name="mcp__cua_screen2__get_browser_state", turn_id="background"
        )
        self.module._pre_llm_call(platform="telegram", turn_id="t1")
        self.module._pre_tool_call(
            tool_name="mcp__cua_screen1__get_browser_state", turn_id="t1"
        )
        self.module._pre_tool_call(tool_name="terminal", turn_id="t1")
        self.assertEqual(self.specialist_events, [])

    def test_specialist_tool_error_is_latched_through_session_end(self):
        turn = {"platform": "telegram", "turn_id": "t1"}
        self.module._pre_llm_call(**turn)
        self.module._pre_tool_call(
            tool_name="mcp__cua_screen3__capture", turn_id="t1"
        )
        self.module._post_tool_call(
            tool_name="mcp__cua_screen3__capture", turn_id="t1",
            status="error", error_message="raw private downstream detail",
        )
        self.assertEqual(self.specialist_events[-1], (
            3, "error", "Specialist tool failed — ready for review"
        ))
        self.module._on_session_end(**turn, completed=True, failed=False)
        self.assertEqual(self.specialist_events[-1], (
            3, "error", "Specialist tool failed — ready for review"
        ))

    def test_specialist_timeout_and_cancellation_fail_closed(self):
        for status in ("timeout", "cancelled"):
            with self.subTest(status=status):
                turn_id = f"turn-{status}"
                turn = {"platform": "telegram", "turn_id": turn_id}
                self.module._pre_llm_call(**turn)
                self.module._pre_tool_call(
                    tool_name="mcp__cua_screen2__get_browser_state",
                    turn_id=turn_id,
                )
                self.module._post_tool_call(
                    tool_name="mcp__cua_screen2__get_browser_state",
                    turn_id=turn_id, status=status,
                )
                self.module._on_session_end(
                    **turn, completed=True, failed=False
                )
                self.assertEqual(self.specialist_events[-1], (
                    2, "error", "Specialist tool failed — ready for review"
                ))

    def test_specialist_session_failure_and_interruption_fail_closed(self):
        outcomes = (
            ({"completed": False, "failed": True},
             "Specialist task failed — ready for review"),
            ({"completed": False, "interrupted": True},
             "Specialist task interrupted — ready for review"),
        )
        for index, (outcome, expected) in enumerate(outcomes):
            with self.subTest(outcome=outcome):
                turn_id = f"terminal-{index}"
                turn = {"platform": "telegram", "turn_id": turn_id}
                self.module._pre_llm_call(**turn)
                self.module._pre_tool_call(
                    tool_name="mcp__cua_screen4__capture", turn_id=turn_id
                )
                self.module._on_session_end(**turn, **outcome)
                self.assertEqual(
                    self.specialist_events[-1], (4, "error", expected)
                )

    def test_specialist_follows_approval_wait_and_resume(self):
        turn = {"platform": "telegram", "turn_id": "t1"}
        self.module._pre_llm_call(**turn)
        self.module._pre_tool_call(
            tool_name="mcp__cua_screen4__capture", turn_id="t1"
        )
        self.module._pre_approval_request(surface="gateway", turn_id="t1")
        self.module._post_approval_response(
            surface="gateway", turn_id="t1", choice="once"
        )
        self.assertEqual(self.specialist_events[-2:], [
            (4, "waiting_approval", "Waiting for owner approval"),
            (4, "working", "Continuing approved task"),
        ])

    def test_iris_latched_error_does_not_leave_other_specialist_waiting(self):
        first = {"platform": "telegram", "turn_id": "t1"}
        second = {"platform": "telegram", "turn_id": "t2"}
        self.module._pre_llm_call(**first)
        self.module._pre_llm_call(**second)
        self.module._pre_tool_call(
            tool_name="mcp__cua_screen4__capture", turn_id="t2"
        )
        self.module._pre_approval_request(surface="gateway", turn_id="t2")
        self.module._post_approval_response(
            surface="gateway", turn_id="t1", choice="deny"
        )
        self.module._post_approval_response(
            surface="gateway", turn_id="t2", choice="once"
        )
        self.assertEqual(self.specialist_events[-1], (
            4, "working", "Continuing approved task"
        ))

    def test_overlapping_specialist_turns_do_not_idle_early(self):
        first = {"platform": "telegram", "turn_id": "t1"}
        second = {"platform": "telegram", "turn_id": "t2"}
        self.module._pre_llm_call(**first)
        self.module._pre_tool_call(
            tool_name="mcp__cua_screen2__get_browser_state", turn_id="t1"
        )
        self.module._pre_llm_call(**second)
        self.module._pre_tool_call(
            tool_name="mcp__cua_screen2__get_browser_state", turn_id="t2"
        )
        self.specialist_events.clear()
        self.module._on_session_end(**first, completed=True, failed=False)
        self.assertEqual(self.specialist_events, [])
        self.module._on_session_end(**second, completed=True, failed=False)
        self.assertEqual(self.specialist_events, [
            (2, "idle", "Ready for recruitment review")
        ])


if __name__ == "__main__":
    unittest.main()
