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
_SPECIALISTS = {
    2: {
        "publisher": os.environ.get(
            "AGENT_SCREEN_STATUS_PUBLISHER_2", "tara-screen-status"
        ),
        "tool_prefix": "mcp__cua_screen2__",
        "working": "Reviewing recruitment workspace",
        "idle": "Ready for recruitment review",
    },
    3: {
        "publisher": os.environ.get(
            "AGENT_SCREEN_STATUS_PUBLISHER_3", "atlas-screen-status"
        ),
        "tool_prefix": "mcp__cua_screen3__",
        "working": "Designing systems workflow",
        "idle": "Ready for strategy work",
    },
    4: {
        "publisher": os.environ.get(
            "AGENT_SCREEN_STATUS_PUBLISHER_4", "mira-screen-status"
        ),
        "tool_prefix": "mcp__cua_screen4__",
        "working": "Working on product design",
        "idle": "Ready for product design work",
    },
}
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
_FAILED_TOOL_STATUSES = {"error", "blocked", "timeout", "cancelled"}
_LOCK = threading.Lock()
_ACTIVE_TURNS: set[str] = set()
_TERMINAL_ERRORS: dict[str, str] = {}
_LATCHED_ERROR: str | None = None
_SPECIALIST_ACTIVE_TURNS: dict[int, set[str]] = {
    screen: set() for screen in _SPECIALISTS
}
_SPECIALIST_TURN_SCREENS: dict[str, set[int]] = {}
_SPECIALIST_ERRORS: dict[tuple[str, int], str] = {}
_SPECIALIST_LATCHED_ERRORS: dict[int, str] = {}


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


def _publish_specialist(screen: int, state: str, task: str) -> None:
    """Publish one specialist state without exposing tool args or results."""
    specialist = _SPECIALISTS.get(screen)
    if specialist is None:
        return
    try:
        subprocess.run(
            [str(specialist["publisher"]), state, task],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
    except Exception:
        # Specialist observability is best-effort and must never affect work.
        pass


def _specialist_screen(tool_name: Any) -> int | None:
    name = str(tool_name or "")
    for screen, specialist in _SPECIALISTS.items():
        if name.startswith(str(specialist["tool_prefix"])):
            return screen
    return None


def _tracked_turn_key(kwargs: dict[str, Any]) -> str | None:
    key = str(kwargs.get("turn_id") or "").strip()
    return key or None


def _pre_tool_call(**kwargs: Any) -> None:
    screen = _specialist_screen(kwargs.get("tool_name"))
    key = _tracked_turn_key(kwargs)
    if screen is None or key is None:
        return
    with _LOCK:
        # Only owner-visible turns admitted by pre_llm_call may own a Screen.
        if key not in _ACTIVE_TURNS:
            return
        screens = _SPECIALIST_TURN_SCREENS.setdefault(key, set())
        first_use = screen not in screens
        screens.add(screen)
        _SPECIALIST_ACTIVE_TURNS[screen].add(key)
        if not first_use:
            return
        latched = _SPECIALIST_LATCHED_ERRORS.get(screen)
        if latched:
            _publish_specialist(screen, "error", latched)
        else:
            _publish_specialist(
                screen, "working", str(_SPECIALISTS[screen]["working"])
            )


def _post_tool_call(**kwargs: Any) -> None:
    screen = _specialist_screen(kwargs.get("tool_name"))
    key = _tracked_turn_key(kwargs)
    if screen is None or key is None:
        return
    status = str(kwargs.get("status") or "").strip().lower()
    if status not in _FAILED_TOOL_STATUSES:
        return
    message = "Specialist tool failed — ready for review"
    with _LOCK:
        if screen not in _SPECIALIST_TURN_SCREENS.get(key, set()):
            return
        _SPECIALIST_ERRORS.setdefault((key, screen), message)
        _SPECIALIST_LATCHED_ERRORS.setdefault(screen, message)
        _publish_specialist(screen, "error", message)


def _finish_specialists_for_turn(
    key: str, *, interrupted: bool = False, failed: bool = False
) -> None:
    screens = _SPECIALIST_TURN_SCREENS.pop(key, set())
    for screen in sorted(screens):
        active = _SPECIALIST_ACTIVE_TURNS[screen]
        active.discard(key)
        terminal_error = _SPECIALIST_ERRORS.pop((key, screen), None)
        if terminal_error:
            _SPECIALIST_LATCHED_ERRORS.setdefault(screen, terminal_error)
        elif interrupted:
            _SPECIALIST_LATCHED_ERRORS.setdefault(
                screen, "Specialist task interrupted — ready for review"
            )
        elif failed:
            _SPECIALIST_LATCHED_ERRORS.setdefault(
                screen, "Specialist task failed — ready for review"
            )
        if active:
            latched = _SPECIALIST_LATCHED_ERRORS.get(screen)
            if latched:
                _publish_specialist(screen, "error", latched)
            continue
        latched = _SPECIALIST_LATCHED_ERRORS.pop(screen, None)
        if latched:
            _publish_specialist(screen, "error", latched)
        else:
            _publish_specialist(
                screen, "idle", str(_SPECIALISTS[screen]["idle"])
            )


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
        _finish_specialists_for_turn(
            key, interrupted=interrupted, failed=failed
        )
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
            for screen in sorted(_SPECIALIST_TURN_SCREENS.get(key, set())):
                latched = _SPECIALIST_LATCHED_ERRORS.get(screen)
                if latched:
                    _publish_specialist(screen, "error", latched)
                else:
                    _publish_specialist(
                        screen, "waiting_approval", "Waiting for owner approval"
                    )


def _post_specialist_approval(key: str, choice: str) -> None:
    """Advance tracked specialists independently of Iris-wide error state."""
    for screen in sorted(_SPECIALIST_TURN_SCREENS.get(key, set())):
        latched = _SPECIALIST_LATCHED_ERRORS.get(screen)
        if choice in _APPROVED_CHOICES and not latched:
            _publish_specialist(screen, "working", "Continuing approved task")
            continue
        if latched:
            specialist_error = latched
        elif choice == "notify_failed":
            specialist_error = "Approval notification failed — ready for review"
        elif choice.startswith("transport_"):
            specialist_error = "Approval transport failed — ready for review"
        elif choice in _DENIED_CHOICES or choice in _TIMEOUT_CHOICES:
            specialist_error = "Approval not granted — ready for review"
        elif choice not in _APPROVED_CHOICES:
            specialist_error = "Unknown approval outcome — ready for review"
        else:
            continue
        _SPECIALIST_ERRORS.setdefault((key, screen), specialist_error)
        _SPECIALIST_LATCHED_ERRORS.setdefault(screen, specialist_error)
        _publish_specialist(screen, "error", specialist_error)


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
            _post_specialist_approval(key, choice)
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
        _post_specialist_approval(key, choice)


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
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("post_llm_call", _post_llm_call)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("pre_approval_request", _pre_approval_request)
    ctx.register_hook("post_approval_response", _post_approval_response)
