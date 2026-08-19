import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class Extents:
    def __init__(self, x, y, width, height):
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class State:
    def __init__(self, *values):
        self.values = set(values)

    def contains(self, value):
        return value in self.values


class Accessible:
    def __init__(self, role, name, extents, *, states=(), children=(), hit=None):
        self.role = role
        self.name = name
        self.extents = Extents(*extents)
        self.state = State(*states)
        self.children = list(children)
        self.hit = hit
        self.child_reads = 0
        self.parent = None
        for child in self.children:
            child.parent = self

    @property
    def childCount(self):
        return len(self.children)

    def getChildAtIndex(self, index):
        self.child_reads += 1
        return self.children[index]

    def getRoleName(self):
        return self.role

    def getState(self):
        return self.state

    def queryComponent(self):
        return self

    def queryCollection(self):
        return Collection(self)

    def getExtents(self, _coordinate_system):
        return self.extents

    def getAccessibleAtPoint(self, _x, _y, _coordinate_system):
        return self.hit


class Collection:
    MATCH_ANY = 1
    MATCH_NONE = 0
    SORT_ORDER_CANONICAL = 0

    def __init__(self, root):
        self.root = root

    def createMatchRule(self, *_args):
        return object()

    def getMatches(self, _rule, _sort_order, _count, _traverse):
        matches = []

        def visit(accessible):
            if accessible.getState().contains("editable"):
                matches.append(accessible)
            for child in accessible.children:
                visit(child)

        visit(self.root)
        return matches


def load_probe():
    pyatspi = types.SimpleNamespace(
        DESKTOP_COORDS=0,
        STATE_ACTIVE="active",
        STATE_EDITABLE="editable",
        STATE_FOCUSABLE="focusable",
        StateSet=lambda *states: set(states),
    )
    spec = importlib.util.spec_from_file_location(
        "accessibility_probe_under_test", ROOT / "bin/accessibility_probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"pyatspi": pyatspi}):
        spec.loader.exec_module(module)
    return module


class AccessibilityProbeTests(unittest.TestCase):
    def test_hit_testing_prefers_active_window_over_overlapping_inactive_frames(self):
        probe = load_probe()
        overlay_panel = Accessible("panel", "", (120, 45, 1000, 35))
        address = Accessible(
            "entry", "Address and search bar", (100, 40, 800, 30), states=("editable",)
        )
        active_window = Accessible(
            "frame",
            "Chrome",
            (0, 0, 1280, 720),
            states=("active",),
            children=(address, overlay_panel),
            hit=overlay_panel,
        )
        inactive_panel = Accessible("panel", "", (120, 45, 1000, 35))
        inactive_window = Accessible(
            "frame",
            "",
            (100, 20, 1100, 100),
            children=(inactive_panel,),
            hit=inactive_panel,
        )
        application = Accessible(
            "application", "Chrome", (0, 0, 1280, 720), children=(active_window, inactive_window)
        )
        desktop = Accessible("desktop frame", "main", (0, 0, 1280, 720), children=(application,))

        result = probe.get_accessible_at_point(desktop, 500, 60)

        self.assertIs(result, address)
        self.assertEqual(inactive_window.child_reads, 0)


if __name__ == "__main__":
    unittest.main()
