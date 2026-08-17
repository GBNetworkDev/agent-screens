#!/usr/bin/env python3
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, "/opt/agent-screen")
from agent_screen.runtime import ScreenSpec, dock_item_names, dock_launcher_specs, wallpaper_path_for_hour, workspace_dir


def spawn(command, env):
    return subprocess.Popen(command, env=env, stdout=sys.stdout, stderr=sys.stderr)


def main():
    spec = ScreenSpec.from_id(int(sys.argv[1]))
    home = Path("/home/agent")
    runtime = Path(spec.runtime_dir)
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    Path(spec.profile_dir).mkdir(mode=0o700, parents=True, exist_ok=True)
    Path(workspace_dir()).mkdir(mode=0o755, parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "DISPLAY": spec.display,
        "HOME": str(home),
        "USER": "agent",
        "LOGNAME": "agent",
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_CONFIG_HOME": str(home / f".config-screen-{spec.screen_id}"),
        "XDG_CACHE_HOME": str(home / f".cache-screen-{spec.screen_id}"),
        "GDK_BACKEND": "x11",
        "LIBGL_ALWAYS_SOFTWARE": "1",
    })

    dock_dir = Path(env["XDG_CONFIG_HOME"]) / "plank/dock1/launchers"
    dock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    for old_launcher in dock_dir.glob("*.dockitem"):
        old_launcher.unlink()
    for filename, desktop_file in dock_launcher_specs():
        (dock_dir / filename).write_text(
            "[PlankDockItemPreferences]\n"
            f"Launcher=file:///home/agent/.local/share/applications/{desktop_file}\n"
        )

    dbus_output = subprocess.check_output(
        ["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"],
        env=env,
        text=True,
    ).strip().splitlines()
    env["DBUS_SESSION_BUS_ADDRESS"] = dbus_output[0]
    (runtime / "session.env").write_text(
        f"DISPLAY={spec.display}\nDBUS_SESSION_BUS_ADDRESS={dbus_output[0]}\n"
        f"XDG_RUNTIME_DIR={runtime}\n"
    )

    processes = []
    xvfb = spawn([
        "Xvfb", spec.display, "-screen", "0", "1280x800x24", "-ac",
        "+extension", "GLX", "+render", "-noreset",
    ], env)
    processes.append(xvfb)

    for _ in range(100):
        if xvfb.poll() is not None:
            raise RuntimeError("Xvfb exited before display became ready")
        if subprocess.run(["xdpyinfo", "-display", spec.display], env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("X display readiness timed out")

    kl_hour = datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).hour
    wallpaper = Path(wallpaper_path_for_hour(kl_hour))
    if wallpaper.is_file():
        subprocess.run(["hsetroot", "-fill", str(wallpaper)], env=env, check=True)
    else:
        subprocess.run(["hsetroot", "-solid", "#202530"], env=env, check=True)
    for key, value in (
        ("/net/launchpad/plank/docks/dock1/theme", "'Transparent'"),
        ("/net/launchpad/plank/docks/dock1/position", "'bottom'"),
        ("/net/launchpad/plank/docks/dock1/icon-size", "48"),
        ("/net/launchpad/plank/docks/dock1/hide-mode", "'none'"),
        ("/net/launchpad/plank/docks/dock1/dock-items", dock_item_names()),
        ("/net/launchpad/plank/docks/dock1/lock-items", "true"),
    ):
        subprocess.run(["dconf", "write", key, value], env=env, check=False)

    commands = [
        ["x11vnc", "-display", spec.display, "-localhost", "-nopw", "-shared",
         "-forever", "-noxdamage", "-rfbport", str(spec.rfb_port)],
        ["websockify", "--web=/usr/share/novnc", "--heartbeat=30",
         f"127.0.0.1:{spec.web_port}", f"127.0.0.1:{spec.rfb_port}"],
        ["xfwm4", "--compositor=off"],
        ["picom", "--backend", "xrender", "--no-vsync", "--no-frame-pacing", "--no-use-damage"],
        ["plank", "--name", "dock1"],
        ["thunar", "--daemon"],
    ]
    for command in commands:
        processes.append(spawn(command, env))

    def stop(_signum=None, _frame=None):
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        deadline = time.time() + 5
        for process in reversed(processes):
            remaining = max(0, deadline - time.time())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while True:
        for process in processes[:5]:
            code = process.poll()
            if code is not None:
                print(f"required process pid={process.pid} exited code={code}", file=sys.stderr)
                stop()
        time.sleep(1)


if __name__ == "__main__":
    main()
