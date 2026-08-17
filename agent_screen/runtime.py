from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenSpec:
    screen_id: int
    display: str
    rfb_port: int
    web_port: int
    cdp_port: int
    runtime_dir: str
    profile_dir: str

    @classmethod
    def from_id(cls, screen_id: int) -> "ScreenSpec":
        if not isinstance(screen_id, int) or not 1 <= screen_id <= 9:
            raise ValueError("screen_id must be between 1 and 9")
        return cls(
            screen_id=screen_id,
            display=f":{screen_id}",
            rfb_port=5900 if screen_id == 1 else 5900 + screen_id,
            web_port=6080 + screen_id,
            cdp_port=9221 + screen_id,
            runtime_dir=f"/tmp/agent-screen-runtime-{screen_id}",
            profile_dir=f"/home/agent/chrome-profile-{screen_id}",
        )


def workspace_dir() -> str:
    return "/workspace"


def wallpaper_path_for_hour(hour: int) -> str:
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        raise ValueError("hour must be between 0 and 23")
    mode = "day" if 7 <= hour < 19 else "night"
    return f"/opt/agent-screen/assets/wallpaper-{mode}.png"


def screen_id_from_display(display: str) -> int:
    if not display.startswith(":"):
        raise ValueError("DISPLAY must use X11 :N notation")
    number = display[1:].split(".", 1)[0]
    if not number.isdigit():
        raise ValueError("DISPLAY must contain a numeric screen id")
    screen_id = int(number)
    ScreenSpec.from_id(screen_id)
    return screen_id


def dock_launcher_specs() -> tuple[tuple[str, str], ...]:
    return (
        ("01-chrome.dockitem", "agent-chrome.desktop"),
        ("02-files.dockitem", "agent-files.desktop"),
        ("03-terminal.dockitem", "agent-terminal.desktop"),
    )


def dock_item_names() -> str:
    names = [filename for filename, _desktop_file in dock_launcher_specs()]
    return "[" + ", ".join(repr(name) for name in names) + "]"


def render_nginx_locations(screen_ids: list[int]) -> str:
    blocks = []
    for screen_id in screen_ids:
        spec = ScreenSpec.from_id(screen_id)
        blocks.append(
            f"""    location = /screen/{screen_id}/ {{
        root /var/www/agent-screen;
        try_files /viewer.html =404;
        default_type text/html;
        add_header Cache-Control \"no-store\" always;
    }}

    location /screen/{screen_id}/core/ {{
        alias /usr/share/novnc/core/;
    }}

    location /screen/{screen_id}/vendor/ {{
        alias /usr/share/novnc/vendor/;
    }}

    location = /screen/{screen_id}/websockify {{
        proxy_pass http://127.0.0.1:{spec.web_port}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection \"upgrade\";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }}"""
        )
    return "\n\n".join(blocks) + "\n"


def viewer_url(host: str, screen_id: int) -> str:
    ScreenSpec.from_id(screen_id)
    return f"https://{host}/screen/{screen_id}/"


def chrome_environment(spec: ScreenSpec) -> dict[str, str]:
    return {
        "DISPLAY": spec.display,
        "HOME": "/home/agent",
        "USER": "agent",
        "LOGNAME": "agent",
        "XDG_RUNTIME_DIR": spec.runtime_dir,
        "GDK_BACKEND": "x11",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "CHROME_DESKTOP": "agent-chrome.desktop",
        "BAMF_DESKTOP_FILE_HINT": "/home/agent/.local/share/applications/agent-chrome.desktop",
    }


def chrome_command(spec: ScreenSpec) -> list[str]:
    return [
        "/usr/bin/google-chrome-stable",
        "--disable-dev-shm-usage",
        "--password-store=basic",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-crash-restore-bubble",
        f"--user-data-dir={spec.profile_dir}",
        "--class=agent-chrome",
        "--enable-unsafe-swiftshader",
        f"--remote-debugging-port={spec.cdp_port}",
        "--remote-debugging-address=127.0.0.1",
        "--new-window",
    ]
