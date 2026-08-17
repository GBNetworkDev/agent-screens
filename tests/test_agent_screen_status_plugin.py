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
        self.events = []
        self.original_publish = self.module._publish
        self.module._publish = lambda state, task: self.events.append((state, task))

    def tearDown(self):
        self.module._publish = self.original_publish
        self.module._ACTIVE_TURNS.clear()

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


if __name__ == "__main__":
    unittest.main()
