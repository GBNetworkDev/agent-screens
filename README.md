# Agent Screens

Persistent, isolated Linux desktops for AI agents and browser automation.

Each screen gets its own X11 display, desktop session, Chrome profile, VNC/WebSocket backend, and Chrome DevTools Protocol endpoint while sharing a single `/workspace` directory.

## Features

- Multiple persistent Xvfb desktops on one Linux host
- Separate Chrome profiles and CDP endpoints per screen
- Minimal XFCE stack with `xfwm4`, Picom, Plank, Thunar, and XFCE Terminal
- Responsive web launcher and clean noVNC viewer
- Optional per-screen agent status cards backed by atomic, bounded JSON updates
- Loopback-only VNC, Websockify, and CDP listeners
- Nginx HTTPS routing with a VPN allowlist
- Kuala Lumpur day/night wallpaper switching
- systemd-managed desktop and Chrome lifecycle
- Python unit tests for port isolation, routing, launchers, and viewer contracts

## Architecture

| Screen | Display | VNC | Websockify | CDP | Chrome profile |
|---|---:|---:|---:|---:|---|
| 1 | `:1` | `5900` | `6081` | `9222` | `/home/agent/chrome-profile-1` |
| 2 | `:2` | `5902` | `6082` | `9223` | `/home/agent/chrome-profile-2` |

All backend ports are intended to listen on `127.0.0.1`. Nginx is the only public-facing entry point.

## Repository layout

- `agent_screen/` — runtime configuration and routing helpers
- `bin/` — desktop, Chrome, wallpaper, and operator commands
- `desktop/` — locked dock launchers
- `systemd/` — service and timer units
- `nginx/` — HTTP, HTTPS, and noVNC routing examples
- `web/` — responsive launcher and viewer
- `assets/` — wallpapers and desktop assets
- `tests/` — unit and contract tests
- `integrations/hermes/` — sanitized SSH bridge for native Hermes Computer Use on both screens

## Requirements

A Debian-based Linux host with:

- Python 3.11+
- Xvfb and X11 utilities
- `x11vnc`, noVNC, and Websockify
- `xfwm4`, Picom, Plank, Thunar, XFCE Terminal, and D-Bus
- Google Chrome
- Nginx and a valid TLS certificate
- An unprivileged `agent` user
- Optional: `cua-driver` installed at `/home/agent/.local/bin/cua-driver` for persistent Computer Use

## Quick start

> **Important:** The checked-in Nginx files use documentation-only values. Replace `screens.example.com`, the certificate paths, and `192.0.2.10` with your own hostname and trusted VPN address before enabling them.

1. Install the required packages and create the `agent` user.
2. Copy the repository to `/opt/agent-screen`.
3. Create `/workspace`, owned by `agent`.
4. Install the desktop launchers under `/home/agent/.local/share/applications/`.
5. Copy the systemd units to `/etc/systemd/system/`.
6. Copy `web/` to `/var/www/agent-screen/`.
7. Customize and enable the Nginx HTTPS configuration.
8. Reload systemd and start the screens:

```bash
sudo install -o root -g root -m 0755 bin/start_cua_screen.sh /usr/local/libexec/start-cua-screen
sudo systemctl daemon-reload
sudo systemctl enable --now agent-screen@1 agent-screen@2
sudo systemctl enable --now agent-screen-chrome@1 agent-screen-chrome@2
sudo systemctl enable --now agent-screen-cua-screen2.service  # optional
```

The Screen 2 CUA unit uses `/home/agent/.cache/cua-driver/cua-driver-screen2.sock`, keeping it isolated from any existing Screen 1 CUA socket.

To connect Hermes to both sockets through native MCP tools without exposing backend listeners, follow the sanitized guide in [`integrations/hermes/README.md`](integrations/hermes/README.md). All real SSH hostnames, ports, identity paths, and credentials stay in the operator environment and must not be committed.

### Optional agent status

The clean viewer can show a compact, live status card for a dedicated screen worker. Publish a bounded status document atomically:

```bash
sudo bin/update_screen_status.py \
  --screen 2 \
  --agent Tara \
  --state idle \
  --task "Ready for recruitment checks"
```

The default output is `/var/www/agent-screen/status/screen-2.json`. Override it with `--output-dir` or `AGENT_SCREEN_STATUS_DIR`. Allowed states are `idle`, `working`, `waiting_approval`, `error`, and `offline`; task text is limited to 120 characters. Keep status text free of secrets and personal data.

Set the hostname used by the operator CLI through the service environment or shell:

```bash
export AGENT_SCREEN_HOST=screens.example.com
```

## Operations

```bash
agent-screen status 1
agent-screen restart 1
agent-screen browser 1
agent-screen screenshot 1 /tmp/screen-1.png
agent-screen url 1
```

## Testing

```bash
python3 -m unittest discover -s tests -v
```

## Security

This project provides remote access to real desktop sessions. Do not expose VNC, Websockify, or CDP directly to the internet. Use a trusted VPN or authenticated access layer and review [SECURITY.md](SECURITY.md) before deployment.

## License

[MIT](LICENSE)
