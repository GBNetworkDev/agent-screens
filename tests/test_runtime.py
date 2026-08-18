import json
import os
import re
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
        text = render_nginx_locations([1, 2, 3, 4])
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
        self.assertIn("location = /screen/3/websockify", text)
        self.assertIn("proxy_pass http://127.0.0.1:6083/;", text)
        self.assertIn("location = /screen/4/websockify", text)
        self.assertIn("proxy_pass http://127.0.0.1:6084/;", text)
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
    def test_screen_two_cua_service_is_persistent_and_isolated(self):
        service = (ROOT / "systemd/agent-screen-cua-screen2.service").read_text()
        launcher = (ROOT / "bin/start_cua_screen.sh").read_text()

        self.assertIn("After=agent-screen@2.service", service)
        self.assertIn("Requires=agent-screen@2.service", service)
        self.assertIn("ExecStart=/usr/local/libexec/start-cua-screen 2", service)
        self.assertIn("WantedBy=multi-user.target", service)
        self.assertIn('DISPLAY=":${screen_id}"', launcher)
        self.assertIn("session.env", launcher)
        self.assertIn('cua-driver-screen2.sock', launcher)
        self.assertIn('cua-driver.sock', launcher)
        self.assertNotIn("0.0.0.0", launcher + service)

    def test_screen_three_and_four_cua_use_isolated_template_sockets(self):
        service = (ROOT / "systemd/agent-screen-cua@.service").read_text()
        launcher = (ROOT / "bin/start_cua_screen.sh").read_text()

        self.assertIn("After=agent-screen@%i.service", service)
        self.assertIn("Requires=agent-screen@%i.service", service)
        self.assertIn("ExecStart=/usr/local/libexec/start-cua-screen %i", service)
        self.assertIn("1|2|3|4", launcher)
        self.assertIn("cua-driver-screen3.sock", launcher)
        self.assertIn("cua-driver-screen4.sock", launcher)
        self.assertNotIn("0.0.0.0", launcher + service)

    def test_sanitized_remote_cua_bridge_supports_four_screens(self):
        local = (ROOT / "integrations/hermes/cua-driver-remote").read_text()
        endpoint = (ROOT / "integrations/hermes/cua-driver-remote-endpoint").read_text()
        screen3 = (ROOT / "integrations/hermes/cua-driver-screen3").read_text()
        screen4 = (ROOT / "integrations/hermes/cua-driver-screen4").read_text()

        self.assertIn("1|2|3|4", local)
        self.assertIn("AGENT_SCREEN_CUA_SOCKET_3", endpoint)
        self.assertIn("AGENT_SCREEN_CUA_SOCKET_4", endpoint)
        self.assertIn("cua-driver-screen3.sock", endpoint)
        self.assertIn("cua-driver-screen4.sock", endpoint)
        self.assertIn("AGENT_SCREEN_CUA_SCREEN=3", screen3)
        self.assertIn("AGENT_SCREEN_CUA_SCREEN=4", screen4)

    def test_static_nginx_examples_route_all_four_screens(self):
        for relative in ("nginx/agent-screen.conf", "nginx/agent-screen-https.conf"):
            config = (ROOT / relative).read_text()
            for screen_id, web_port in ((1, 6081), (2, 6082), (3, 6083), (4, 6084)):
                self.assertIn(f"/screen/{screen_id}/", config)
                self.assertIn(f"127.0.0.1:{web_port}", config)

    def test_sanitized_hermes_bridge_has_configurable_public_defaults(self):
        local = (ROOT / "integrations/hermes/cua-driver-remote").read_text()
        endpoint = (ROOT / "integrations/hermes/cua-driver-remote-endpoint").read_text()
        rewrite = (ROOT / "integrations/hermes/rewrite_cua_manifest.py").read_text()
        docs = (ROOT / "integrations/hermes/README.md").read_text()
        combined = local + endpoint + rewrite + docs

        self.assertIn("AGENT_SCREEN_SSH_HOST", local)
        self.assertIn("AGENT_SCREEN_SSH_PORT", local)
        self.assertIn("AGENT_SCREEN_SSH_IDENTITY", local)
        self.assertIn("AGENT_SCREEN_CUA_SCREEN", local)
        self.assertIn("AGENT_SCREEN_REMOTE_ENDPOINT", local)
        self.assertIn("AGENT_SCREEN_CUA_SOCKET_1", endpoint)
        self.assertIn("AGENT_SCREEN_CUA_SOCKET_2", endpoint)
        self.assertIn("binary_path", rewrite)
        self.assertIn("screens.example.com", docs)
        self.assertIn("cua_screen1", docs)
        self.assertIn("cua_screen2", docs)
        self.assertIn("Status ownership follows the actual worker", docs)
        self.assertIn("before the first specialist work action", docs)
        self.assertIn("`working`", docs)
        self.assertIn("`idle`, `waiting_approval`, or `error`", docs)
        ipv4_addresses = set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", combined))
        documentation_prefixes = ("192.0.2.", "198.51.100.", "203.0.113.")
        self.assertTrue(
            all(address.startswith(documentation_prefixes) for address in ipv4_addresses),
            f"non-documentation IP address found: {sorted(ipv4_addresses)}",
        )

    def test_clean_viewer_and_landing_have_no_legacy_novnc_pages(self):
        viewer = (ROOT / "web/viewer.html").read_text()
        landing = (ROOT / "web/index.html").read_text()
        self.assertIn('import RFB from "./core/rfb.js";', viewer)
        self.assertIn('id="mobile-keyboard-button"', viewer)
        self.assertIn('id="mobile-keyboard-input"', viewer)
        self.assertIn('id="mobile-clipboard-button"', viewer)
        self.assertIn('data-icon="clipboard-paste"', viewer)
        self.assertIn('class="clipboard-paste-arrow"', viewer)
        self.assertIn('#mobile-keyboard-button,#mobile-clipboard-button{width:48px;height:44px;min-width:48px;min-height:44px', viewer)
        self.assertIn('background:#111827e8;color:#f8fafc;box-shadow:0 8px 24px #0008', viewer)
        self.assertIn('#mobile-clipboard-button svg{width:20px;height:20px}', viewer)
        self.assertNotIn('linear-gradient(145deg,#1e3a5f', viewer)
        self.assertIn('aria-label="Paste clipboard to remote screen"', viewer)
        self.assertIn('id="mobile-clipboard-fallback"', viewer)
        self.assertIn('id="mobile-clipboard-input"', viewer)
        self.assertIn('navigator.clipboard.readText()', viewer)
        self.assertIn('rfb.clipboardPasteFrom(text)', viewer)
        self.assertIn('sendRemotePasteShortcut()', viewer)
        self.assertIn('id="screen-switcher"', viewer)
        self.assertIn('href="/screen/1/"', viewer)
        self.assertIn('href="/screen/2/"', viewer)
        self.assertIn('href="/screen/3/"', viewer)
        self.assertIn('href="/screen/4/"', viewer)
        self.assertIn('data-screen="1"', viewer)
        self.assertIn('data-screen="2"', viewer)
        self.assertIn('data-screen="3"', viewer)
        self.assertIn('data-screen="4"', viewer)
        self.assertIn('setAttribute("aria-current", "page")', viewer)
        self.assertIn('env(safe-area-inset-top)', viewer)
        self.assertIn('white-space:nowrap', viewer)
        self.assertIn('id="agent-status"', viewer)
        self.assertIn('data-agent="Iris"', viewer)
        self.assertIn('data-agent="Tara"', viewer)
        self.assertIn('data-agent="Atlas"', viewer)
        self.assertIn('data-agent="Mira"', viewer)
        self.assertIn('/status/screen-${screenNumber}.json', viewer)
        self.assertIn('cache: "no-store"', viewer)
        self.assertIn('payload.screen !== Number(screenNumber)', viewer)
        self.assertIn('inputmode="text"', viewer)
        self.assertIn("rfb.sendKey", viewer)
        self.assertIn("scaleViewport = true", viewer)
        self.assertIn("resizeSession = false", viewer)
        self.assertIn("showDotCursor = true", viewer)
        self.assertIn("setTimeout(connect, 2000)", viewer)
        self.assertIn('href="/screen/1/"', landing)
        self.assertIn('href="/screen/2/"', landing)
        self.assertIn('href="/screen/3/"', landing)
        self.assertIn('href="/screen/4/"', landing)
        self.assertIn("4 screens available", landing)
        combined = viewer + landing
        self.assertNotIn("vnc.html", combined)
        self.assertNotIn("vnc_lite.html", combined)

    def test_viewer_has_unified_agent_command_header(self):
        viewer = (ROOT / "web/viewer.html").read_text()

        self.assertIn('id="agent-command-header"', viewer)
        self.assertIn('data-agent-name="Iris"', viewer)
        self.assertIn('data-agent-role="Chief of Staff"', viewer)
        self.assertIn('data-agent-name="Tara"', viewer)
        self.assertIn('data-agent-role="Recruitment Agent"', viewer)
        self.assertIn('data-agent-name="Atlas"', viewer)
        self.assertIn('data-agent-role="GBAsset &amp; EasyDCIM Agent"', viewer)
        self.assertIn('data-agent-name="Mira"', viewer)
        self.assertIn('data-agent-role="Product Design &amp; UX Agent"', viewer)
        self.assertIn('#screen-switcher a[data-screen="1"] .screen-link-dot{background:#8b5cf6;box-shadow:0 0 0 3px #8b5cf633}', viewer)
        self.assertIn('#screen-switcher a[data-screen="2"] .screen-link-dot{background:#0ea5e9;box-shadow:0 0 0 3px #0ea5e933}', viewer)
        self.assertIn('#screen-switcher a[data-screen="3"] .screen-link-dot{background:#22c55e;box-shadow:0 0 0 3px #22c55e33}', viewer)
        self.assertIn('#screen-switcher a[data-screen="4"] .screen-link-dot{background:#ec4899;box-shadow:0 0 0 3px #ec489933}', viewer)
        self.assertIn('#screen-switcher a:not([aria-current="page"]) .screen-link-dot{opacity:.72}', viewer)
        self.assertIn('@media (max-width:480px){#agent-command-header{left:8px;right:8px;width:auto;transform:none}', viewer)
        self.assertIn('#agent-command-header[data-collapsed="true"]{left:50%;right:auto;width:min(340px,calc(100vw - 32px));transform:translateX(-50%)}', viewer)
        self.assertIn('#agent-command-header[data-collapsed="true"] #agent-status{column-gap:12px;padding:11px 52px 11px 15px}', viewer)
        self.assertIn('#agent-command-header[data-collapsed="true"] #agent-status-state{align-self:center}', viewer)
        self.assertIn('@media (max-width:480px){#agent-command-header{left:8px;right:8px;width:auto;transform:none}#agent-header-toggle{background:transparent!important;box-shadow:none;-webkit-tap-highlight-color:transparent}', viewer)
        self.assertIn('#agent-command-header[data-collapsed="true"] #agent-header-toggle{right:4px;top:50%;bottom:auto;width:40px;height:40px;background:transparent!important;box-shadow:none;-webkit-tap-highlight-color:transparent;transform:translateY(-50%) rotate(180deg)}', viewer)
        self.assertIn('id="agent-status-role"', viewer)
        self.assertIn('id="agent-status-activity"', viewer)
        self.assertIn('id="screen-connection-state"', viewer)
        self.assertIn('id="agent-header-toggle"', viewer)
        self.assertIn('aria-expanded="true"', viewer)
        self.assertIn('data-collapsed="false"', viewer)
        self.assertIn('#agent-header-toggle{position:absolute;right:0;bottom:0;width:44px;height:44px', viewer)

    def test_viewer_loads_status_for_both_agent_screens(self):
        viewer = (ROOT / "web/viewer.html").read_text()

        self.assertIn('/status/screen-${screenNumber}.json', viewer)
        self.assertIn('payload.screen !== Number(screenNumber)', viewer)
        self.assertIn('payload.agent !== activeAgent.name', viewer)
        self.assertIn('idle: "Ready"', viewer)
        self.assertIn('setInterval(refreshAgentStatus, 5000)', viewer)
        self.assertNotIn('screenNumber === "2"', viewer)

    def test_viewer_reports_live_and_reconnecting_screen_connection(self):
        viewer = (ROOT / "web/viewer.html").read_text()

        self.assertIn('addEventListener("connect"', viewer)
        self.assertIn('setConnectionState("live")', viewer)
        self.assertIn('setConnectionState("reconnecting")', viewer)
        self.assertIn('Screen Live', viewer)
        self.assertIn('Reconnecting', viewer)

    def test_status_writer_emits_atomic_bounded_json(self):
        script = ROOT / "bin/update_screen_status.py"
        self.assertTrue(script.exists())
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--output-dir",
                    directory,
                    "--screen",
                    "2",
                    "--agent",
                    "Tara",
                    "--state",
                    "working",
                    "--task",
                    "Checking Indeed applicants",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            status_path = Path(directory) / "screen-2.json"
            payload = json.loads(status_path.read_text())
            self.assertEqual(payload["schema"], 1)
            self.assertEqual(payload["screen"], 2)
            self.assertEqual(payload["agent"], "Tara")
            self.assertEqual(payload["state"], "working")
            self.assertEqual(payload["task"], "Checking Indeed applicants")
            self.assertRegex(payload["updated_at"], r"^\d{4}-\d{2}-\d{2}T")
            self.assertEqual(status_path.stat().st_mode & 0o777, 0o644)
            self.assertIn(str(status_path), result.stdout)
            self.assertFalse(list(Path(directory).glob("*.tmp")))

    def test_status_writer_rejects_invalid_state_and_long_task(self):
        script = ROOT / "bin/update_screen_status.py"
        with tempfile.TemporaryDirectory() as directory:
            invalid = subprocess.run(
                [sys.executable, str(script), "--output-dir", directory, "--screen", "2", "--agent", "Tara", "--state", "busy", "--task", "Test"],
                capture_output=True,
                text=True,
            )
            too_long = subprocess.run(
                [sys.executable, str(script), "--output-dir", directory, "--screen", "2", "--agent", "Tara", "--state", "working", "--task", "x" * 121],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertNotEqual(too_long.returncode, 0)


if __name__ == "__main__":
    unittest.main()
