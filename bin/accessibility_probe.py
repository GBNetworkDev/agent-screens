#!/usr/bin/python3
"""Loopback-only AT-SPI hit testing for mobile keyboard hints."""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pyatspi


EDITABLE_ROLES = {
    "entry",
    "password text",
    "search box",
    "spin button",
    "text",
}
MAX_COORDINATE = 16384


def _children(accessible):
    try:
        return [accessible.getChildAtIndex(index) for index in range(accessible.childCount)]
    except Exception:
        return []


def _point_area(accessible, x, y):
    try:
        extents = accessible.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
        if extents.width > 0 and extents.height > 0 and (
            extents.x <= x < extents.x + extents.width
            and extents.y <= y < extents.y + extents.height
        ):
            return extents.width * extents.height
    except Exception:
        pass
    return None


def _is_active(accessible):
    try:
        return accessible.getState().contains(pyatspi.STATE_ACTIVE)
    except Exception:
        return False


def _top_level_candidates(desktop, x, y):
    """Return point-containing application windows, active window first."""
    candidates = []
    for application in _children(desktop):
        for window in _children(application):
            area = _point_area(window, x, y)
            if area is not None:
                candidates.append((not _is_active(window), area, window))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in candidates]


def _editable_at_point(window, x, y):
    """Use AT-SPI's server-side collection query to avoid a full tree walk."""
    try:
        collection = window.queryCollection()
        rule = collection.createMatchRule(
            pyatspi.StateSet(pyatspi.STATE_EDITABLE),
            collection.MATCH_ANY,
            [],
            collection.MATCH_NONE,
            [],
            collection.MATCH_NONE,
            [],
            collection.MATCH_NONE,
            False,
        )
        matches = collection.getMatches(
            rule, collection.SORT_ORDER_CANONICAL, 0, True
        )
    except Exception:
        return None
    containing = []
    for accessible in matches:
        area = _point_area(accessible, x, y)
        if area is not None:
            containing.append((area, accessible))
    return min(containing, key=lambda item: item[0])[1] if containing else None


def _deepest_at_point(accessible, x, y):
    """Descend through the component API without walking the whole tree."""
    current = accessible
    descended = False
    for _depth in range(32):
        try:
            candidate = current.queryComponent().getAccessibleAtPoint(
                x, y, pyatspi.DESKTOP_COORDS
            )
        except Exception:
            break
        if candidate is None or candidate == current:
            break
        current = candidate
        descended = True
    return current if descended else None


def get_accessible_at_point(desktop, x, y):
    """Return the deepest accessible in the active point-containing window."""
    for window in _top_level_candidates(desktop, x, y):
        editable = _editable_at_point(window, x, y)
        if editable is not None:
            return editable
        accessible = _deepest_at_point(window, x, y)
        if accessible is not None:
            return accessible
    return None


def editable_details(accessible):
    """Classify the hit object or a nearby ancestor as text editable."""
    current = accessible
    for _depth in range(8):
        if current is None:
            break
        try:
            role = (current.getRoleName() or "").strip().lower()
            state = current.getState()
            editable = state.contains(pyatspi.STATE_EDITABLE)
            focusable = state.contains(pyatspi.STATE_FOCUSABLE)
            if editable or (role in EDITABLE_ROLES and focusable):
                return {
                    "editable": True,
                    "role": role,
                    "name": (current.name or "")[:120],
                }
            current = current.parent
        except Exception:
            break
    role = ""
    name = ""
    if accessible is not None:
        try:
            role = (accessible.getRoleName() or "").strip().lower()
            name = (accessible.name or "")[:120]
        except Exception:
            pass
    return {"editable": False, "role": role, "name": name}


def hit_test(x, y):
    desktop = pyatspi.Registry.getDesktop(0)
    accessible = get_accessible_at_point(desktop, x, y)
    return editable_details(accessible)


class ProbeHandler(BaseHTTPRequestHandler):
    server_version = "AgentScreenInputProbe/1"

    def _json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"ok": True})
            return
        if parsed.path != "/hit-test":
            self._json(404, {"error": "not-found"})
            return
        try:
            query = parse_qs(parsed.query, strict_parsing=True)
            x = int(query["x"][0])
            y = int(query["y"][0])
            if not 0 <= x <= MAX_COORDINATE or not 0 <= y <= MAX_COORDINATE:
                raise ValueError("coordinate-out-of-range")
            self._json(200, hit_test(x, y))
        except (KeyError, ValueError, IndexError):
            self._json(400, {"error": "invalid-coordinates"})
        except Exception:
            self._json(503, {"error": "accessibility-unavailable"})

    def log_message(self, format, *args):
        del format, args
        return


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: accessibility_probe.py SCREEN_ID")
    screen_id = int(sys.argv[1])
    if not 1 <= screen_id <= 9:
        raise SystemExit("SCREEN_ID must be between 1 and 9")
    port = 6090 + screen_id
    server = HTTPServer(("127.0.0.1", port), ProbeHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
