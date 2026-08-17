#!/usr/bin/env python3
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, "/opt/agent-screen")
from agent_screen.runtime import wallpaper_path_for_hour


def main():
    hour = datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).hour
    wallpaper = Path(wallpaper_path_for_hour(hour))
    if not wallpaper.is_file():
        raise SystemExit(f"missing wallpaper: {wallpaper}")

    mode = "day" if 7 <= hour < 19 else "night"
    for screen_id in (1, 2):
        runtime = Path(f"/tmp/agent-screen-runtime-{screen_id}")
        if not (runtime / "session.env").is_file():
            continue
        env = os.environ.copy()
        env.update({
            "DISPLAY": f":{screen_id}",
            "HOME": "/home/agent",
            "USER": "agent",
            "LOGNAME": "agent",
            "XDG_RUNTIME_DIR": str(runtime),
        })
        subprocess.run(
            ["runuser", "-u", "agent", "--", "env", *[f"{k}={v}" for k, v in env.items()],
             "hsetroot", "-fill", str(wallpaper)],
            check=True,
        )
    Path("/run/agent-screen-wallpaper-mode").write_text(mode + "\n")
    print(f"mode={mode} hour_kl={hour} wallpaper={wallpaper}")


if __name__ == "__main__":
    main()
