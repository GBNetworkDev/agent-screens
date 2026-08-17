import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ScreenRuntimeTests(unittest.TestCase):
    def test_screen_one_uses_primary_ports(self):
        from agent_screen.runtime import ScreenSpec
        spec = ScreenSpec.from_id(1)
        self.assertEqual(spec.display, ":1")
        self.assertEqual(spec.rfb_port, 5900)
        self.assertEqual(spec.web_port, 6081)
        self.assertEqual(spec.cdp_port, 9222)
        self.assertEqual(spec.profile_dir, "/home/agent/chrome-profile-1")

    def test_screen_two_has_distinct_ports_and_runtime(self):
        from agent_screen.runtime import ScreenSpec
        spec = ScreenSpec.from_id(2)
        self.assertEqual((spec.rfb_port, spec.web_port, spec.cdp_port), (5902, 6082, 9223))
        self.assertEqual(spec.runtime_dir, "/tmp/agent-screen-runtime-2")

    def test_rejects_out_of_range_screen_ids(self):
        from agent_screen.runtime import ScreenSpec
        for value in (0, 10, -1):
            with self.assertRaises(ValueError):
                ScreenSpec.from_id(value)

    def test_nginx_locations_serve_clean_viewer_and_scoped_websocket(self):
        from agent_screen.runtime import render_nginx_locations
        text = render_nginx_locations([1, 2])
        self.assertIn("location = /screen/1/", text)
        self.assertIn("root /var/www/agent-screen;", text)
        self.assertIn("try_files /viewer.html =404;", text)
        self.assertIn("location /screen/1/core/", text)
        self.assertIn("alias /usr/share/novnc/core/;", text)
        self.assertIn("location /screen/1/vendor/", text)
        self.assertIn("location = /screen/1/websockify", text)
        self.assertIn("proxy_pass http://127.0.0.1:6081/;", text)
        self.assertIn("location = /screen/2/websockify", text)
        self.assertIn("proxy_pass http://127.0.0.1:6082/;", text)
        self.assertNotIn("5900", text)
        self.assertNotIn("9222", text)

    def test_viewer_urls_use_clean_screen_path(self):
        from agent_screen.runtime import viewer_url
        self.assertEqual(
            viewer_url("screens.example.com", 2),
            "https://screens.example.com/screen/2/",
        )

    def test_chrome_command_keeps_cdp_on_loopback_and_separate_profile(self):
        from agent_screen.runtime import ScreenSpec, chrome_command
        command = chrome_command(ScreenSpec.from_id(3))
        self.assertIn("--remote-debugging-address=127.0.0.1", command)
        self.assertIn("--remote-debugging-port=9224", command)
        self.assertIn("--user-data-dir=/home/agent/chrome-profile-3", command)
        self.assertIn("--class=agent-chrome", command)
        self.assertNotIn("--enable-automation", command)

    def test_all_screens_share_standalone_workspace(self):
        from agent_screen.runtime import workspace_dir
        self.assertEqual(workspace_dir(), "/workspace")

    def test_wallpaper_switches_by_kuala_lumpur_hour(self):
        from agent_screen.runtime import wallpaper_path_for_hour
        self.assertEqual(
            wallpaper_path_for_hour(7),
            "/opt/agent-screen/assets/wallpaper-day.png",
        )
        self.assertEqual(
            wallpaper_path_for_hour(18),
            "/opt/agent-screen/assets/wallpaper-day.png",
        )
        self.assertEqual(
            wallpaper_path_for_hour(19),
            "/opt/agent-screen/assets/wallpaper-night.png",
        )
        self.assertEqual(
            wallpaper_path_for_hour(6),
            "/opt/agent-screen/assets/wallpaper-night.png",
        )

    def test_screen_id_can_be_derived_from_display(self):
        from agent_screen.runtime import screen_id_from_display
        self.assertEqual(screen_id_from_display(":1"), 1)
        self.assertEqual(screen_id_from_display(":2.0"), 2)
        with self.assertRaises(ValueError):
            screen_id_from_display("wayland-0")

    def test_chrome_environment_matches_persistent_dock_launcher(self):
        from agent_screen.runtime import ScreenSpec, chrome_environment
        env = chrome_environment(ScreenSpec.from_id(2))
        self.assertEqual(env["CHROME_DESKTOP"], "agent-chrome.desktop")
        self.assertEqual(
            env["BAMF_DESKTOP_FILE_HINT"],
            "/home/agent/.local/share/applications/agent-chrome.desktop",
        )

    def test_session_environment_waits_for_desktop_readiness(self):
        from agent_screen.runtime import read_session_environment

        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "session.env"
            sleep_calls = []

            def create_environment(_delay):
                sleep_calls.append(1)
                env_file.write_text(
                    "DISPLAY=:1\n"
                    "DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/dbus-test\n"
                    "XDG_RUNTIME_DIR=/tmp/agent-screen-runtime-1\n"
                )

            env = read_session_environment(
                env_file,
                attempts=2,
                delay=0,
                sleep=create_environment,
            )

        self.assertEqual(len(sleep_calls), 1)
        self.assertEqual(env["DISPLAY"], ":1")
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/tmp/dbus-test")
        self.assertEqual(env["XDG_RUNTIME_DIR"], "/tmp/agent-screen-runtime-1")

    def test_dock_layout_is_locked_to_three_ordered_launchers(self):
        from agent_screen.runtime import dock_item_names, dock_launcher_specs
        self.assertEqual(
            dock_launcher_specs(),
            (
                ("01-chrome.dockitem", "agent-chrome.desktop"),
                ("02-files.dockitem", "agent-files.desktop"),
                ("03-terminal.dockitem", "agent-terminal.desktop"),
            ),
        )
        self.assertEqual(
            dock_item_names(),
            "['01-chrome.dockitem', '02-files.dockitem', '03-terminal.dockitem']",
        )
    def test_thunar_launcher_uses_native_thunar_icon(self):
        desktop = (ROOT / "desktop/agent-files.desktop").read_text()
        self.assertIn(
            "Icon=/usr/share/icons/hicolor/128x128/apps/org.xfce.thunar.png",
            desktop,
        )

    def test_thunar_launcher_is_named_thunar_file_manager(self):
        desktop = (ROOT / "desktop/agent-files.desktop").read_text()
        self.assertIn("Name=Thunar File Manager", desktop)
        self.assertNotIn("Name=Files\n", desktop)
    def test_clean_viewer_and_landing_have_no_legacy_novnc_pages(self):
        viewer = (ROOT / "web/viewer.html").read_text()
        landing = (ROOT / "web/index.html").read_text()
        self.assertIn('import RFB from "./core/rfb.js";', viewer)
        self.assertIn('id="mobile-keyboard-button"', viewer)
        self.assertIn('id="mobile-keyboard-input"', viewer)
        self.assertIn('inputmode="text"', viewer)
        self.assertIn("rfb.sendKey", viewer)
        self.assertIn("scaleViewport = true", viewer)
        self.assertIn("resizeSession = false", viewer)
        self.assertIn("showDotCursor = true", viewer)
        self.assertIn("setTimeout(connect, 2000)", viewer)
        self.assertIn('href="/screen/1/"', landing)
        self.assertIn('href="/screen/2/"', landing)
        combined = viewer + landing
        self.assertNotIn("vnc.html", combined)
        self.assertNotIn("vnc_lite.html", combined)


if __name__ == "__main__":
    unittest.main()
