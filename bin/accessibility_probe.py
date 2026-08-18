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


def _contains_point(accessible, x, y):
    return _point_area(accessible, x, y) is not None


def _deepest_containing(accessible, x, y, depth=0):
    if depth > 32:
        return None
    best = accessible if _contains_point(accessible, x, y) else None
    best_area = _point_area(best, x, y) if best is not None else None
    for child in _children(accessible):
        candidate = _deepest_containing(child, x, y, depth + 1)
        if candidate is None:
            continue
        candidate_area = _point_area(candidate, x, y)
        if best is None or best_area is None or (
            candidate_area is not None and candidate_area <= best_area
        ):
            best = candidate
            best_area = candidate_area
    return best


def get_accessible_at_point(desktop, x, y):
    """Return the deepest visible accessible at desktop coordinates."""
    accessible = _deepest_containing(desktop, x, y)
    if accessible is None or accessible == desktop:
        return None
    for _depth in range(16):
        try:
            candidate = accessible.queryComponent().getAccessibleAtPoint(
                x, y, pyatspi.DESKTOP_COORDS
            )
        except Exception:
            break
        if candidate is None or candidate == accessible:
            break
        accessible = candidate
    return accessible


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
