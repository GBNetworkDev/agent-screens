"""Publish top-level Hermes turn lifecycle to an Agent Screens status writer.

The plugin never publishes raw prompts or responses. It maps owner-visible
turns to a bounded vocabulary and ignores background review/subagent forks.
"""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

_PUBLISHER = os.environ.get("AGENT_SCREEN_STATUS_PUBLISHER", "iris-screen-status")
_SUPPORTED_PLATFORMS = {
    value.strip().lower()
    for value in os.environ.get(
        "AGENT_SCREEN_STATUS_PLATFORMS",
        "telegram,discord,slack,email,webhook,api,homeassistant,cron,cli,tui,desktop,acp",
    ).split(",")
    if value.strip()
}
_APPROVAL_SURFACES = {"gateway", "cli", "smart"}
_APPROVED_CHOICES = {"always", "approve", "approved", "once", "session", "smart_approve"}
_DENIED_CHOICES = {"deny", "denied", "smart_deny"}
_TIMEOUT_CHOICES = {"timed_out", "timeout"}
_LOCK = threading.Lock()
_ACTIVE_TURNS: set[str] = set()
_TERMINAL_ERRORS: dict[str, str] = {}
_LATCHED_ERROR: str | None = None


def _turn_key(kwargs: dict[str, Any]) -> str:
    return str(
        kwargs.get("turn_id")
        or f"{kwargs.get('session_id', 'unknown')}:{threading.get_ident()}"
    )


def _in_scope(kwargs: dict[str, Any]) -> bool:
    # Background skill/memory review agents inherit the parent's platform and
    # session id. parent_session_id distinguishes them from owner-visible work.
    if str(kwargs.get("parent_session_id") or "").strip():
        return False
    platform = str(kwargs.get("platform") or "").lower()
    return platform in _SUPPORTED_PLATFORMS


def _approval_in_scope(kwargs: dict[str, Any]) -> bool:
    if str(kwargs.get("parent_session_id") or "").strip():
        return False
    platform = str(kwargs.get("platform") or "").lower()
    surface = str(kwargs.get("surface") or "").lower()
    transport_name = surface.removeprefix("transport:").strip()
    is_transport = surface.startswith("transport:") and bool(transport_name)
    return (
        platform in _SUPPORTED_PLATFORMS
        or surface in _APPROVAL_SURFACES
        or is_transport
    )


def _approval_turn_key(kwargs: dict[str, Any]) -> str | None:
    turn_id = str(kwargs.get("turn_id") or "").strip()
    return turn_id or None


def _safe_task(message: Any) -> str:
    """Map prompt keywords to bounded labels without copying prompt content."""
    text = message.lower() if isinstance(message, str) else ""
    labels = (
        (("speedtest", "speed test"), "Running network speed test"),
        (("status", "island", "header"), "Updating Agent Screen status"),
        (("candidate", "recruit"), "Coordinating recruitment check"),
        (("github", "pull request", "commit", "repo"), "Working on code repository"),
        (("home assistant", "sensor", "aircond"), "Checking smart home"),
        (("email", "inbox"), "Reviewing communications"),
        (("server", "systemd", "service"), "Checking system operations"),
    )
    for keywords, label in labels:
        if any(keyword in text for keyword in keywords):
            return label
    return "Handling owner request"


def _publish(state: str, task: str) -> None:
    """Publish synchronously so status changes precede lifecycle changes."""
    try:
        subprocess.run(
            [_PUBLISHER, state, task],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
    except Exception:
        # Publisher failure must never break the agent turn; subprocess timeout
        # bounds any synchronous observability delay.
        pass


def _publish_unless_latched(state: str, task: str) -> None:
    if _LATCHED_ERROR:
        _publish("error", _LATCHED_ERROR)
    else:
        _publish(state, task)


def _pre_llm_call(**kwargs: Any) -> None:
    global _LATCHED_ERROR
    if not _in_scope(kwargs):
        return
    key = _turn_key(kwargs)
    message = kwargs.get("user_message", kwargs.get("message", ""))
    with _LOCK:
        if not _ACTIVE_TURNS:
            _LATCHED_ERROR = None
        is_new_turn = key not in _ACTIVE_TURNS
        _ACTIVE_TURNS.add(key)
        if is_new_turn:
            _TERMINAL_ERRORS.pop(key, None)
        _publish_unless_latched("working", _safe_task(message))


def _finish_turn(*, interrupted: bool = False, failed: bool = False, **kwargs: Any) -> None:
    global _LATCHED_ERROR
    if not _in_scope(kwargs):
        return
    key = _turn_key(kwargs)
    with _LOCK:
        if key not in _ACTIVE_TURNS:
            return
        _ACTIVE_TURNS.remove(key)
        terminal_error = _TERMINAL_ERRORS.pop(key, None)
        if terminal_error and _LATCHED_ERROR is None:
            _LATCHED_ERROR = terminal_error
        elif interrupted and _LATCHED_ERROR is None:
            _LATCHED_ERROR = "Turn interrupted — ready for review"
        elif failed and _LATCHED_ERROR is None:
            _LATCHED_ERROR = "Turn failed — ready for review"
        if _ACTIVE_TURNS:
            return
        if _LATCHED_ERROR:
            message = _LATCHED_ERROR
            _LATCHED_ERROR = None
            _publish("error", message)
        else:
            _publish("idle", "Ready to coordinate operations")


def _post_llm_call(**kwargs: Any) -> None:
    # on_session_end carries the authoritative completed/failed/interrupted
    # outcome and always fires at the end of run_conversation. Finalizing here
    # would erase denial/failure state before that terminal outcome arrives.
    return None


def _on_session_end(**kwargs: Any) -> None:
    if not _in_scope(kwargs):
        return
    key = _turn_key(kwargs)
    with _LOCK:
        is_still_active = key in _ACTIVE_TURNS
    if not is_still_active:
        return
    failed = bool(kwargs.get("failed"))
    interrupted = bool(kwargs.get("interrupted")) or (
        kwargs.get("completed") is False and not failed
    )
    payload = dict(kwargs)
    payload.pop("interrupted", None)
    payload.pop("failed", None)
    _finish_turn(interrupted=interrupted, failed=failed, **payload)


def _pre_approval_request(**kwargs: Any) -> None:
    if not _approval_in_scope(kwargs):
        return
    key = _approval_turn_key(kwargs)
    if key is None:
        return
    with _LOCK:
        if key in _ACTIVE_TURNS:
            _publish_unless_latched(
                "waiting_approval", "Waiting for owner approval"
            )


def _post_approval_response(**kwargs: Any) -> None:
    global _LATCHED_ERROR
    if not _approval_in_scope(kwargs):
        return
    key = _approval_turn_key(kwargs)
    if key is None:
        return
    choice = str(kwargs.get("choice") or "").strip().lower()
    with _LOCK:
        if key not in _ACTIVE_TURNS:
            return
        if _LATCHED_ERROR:
            _publish("error", _LATCHED_ERROR)
            return
        if choice == "notify_failed":
            message = "Approval notification failed — ready for review"
            _TERMINAL_ERRORS.setdefault(key, message)
            if _LATCHED_ERROR is None:
                _LATCHED_ERROR = message
            _publish("error", message)
        elif choice.startswith("transport_"):
            message = "Approval transport failed — ready for review"
            _TERMINAL_ERRORS.setdefault(key, message)
            if _LATCHED_ERROR is None:
                _LATCHED_ERROR = message
            _publish("error", message)
        elif choice in _DENIED_CHOICES or choice in _TIMEOUT_CHOICES:
            message = "Approval not granted — ready for review"
            _TERMINAL_ERRORS.setdefault(key, message)
            if _LATCHED_ERROR is None:
                _LATCHED_ERROR = message
            _publish("error", message)
        elif choice in _APPROVED_CHOICES:
            terminal_error = _TERMINAL_ERRORS.get(key)
            if terminal_error:
                _publish("error", terminal_error)
            else:
                _publish("working", "Continuing approved task")
        else:
            message = "Unknown approval outcome — ready for review"
            _TERMINAL_ERRORS.setdefault(key, message)
            if _LATCHED_ERROR is None:
                _LATCHED_ERROR = message
            _publish("error", message)


def _on_session_start(**kwargs: Any) -> None:
    if not _in_scope(kwargs):
        return
    with _LOCK:
        active = bool(_ACTIVE_TURNS)
        if not active:
            _publish("idle", "Ready to coordinate operations")


def register(ctx: Any) -> None:
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_hook("post_llm_call", _post_llm_call)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("pre_approval_request", _pre_approval_request)
    ctx.register_hook("post_approval_response", _post_approval_response)
