# Security Policy

Agent Screens exposes interactive Linux desktops and browser debugging endpoints. Treat every deployment as privileged infrastructure.

## Deployment requirements

- Keep raw VNC, Websockify backends, and Chrome DevTools Protocol listeners on loopback.
- Restrict the HTTPS viewer to a trusted VPN or authenticated reverse proxy.
- Replace every example hostname, certificate path, and allowlisted address before deployment.
- Never commit browser profiles, cookies, environment files, private keys, screenshots, or runtime state.
- Do not launch Chrome with `--no-sandbox` on a normal Linux host.
- Apply operating-system and browser security updates regularly.

## Reporting a vulnerability

Please report security issues privately through GitHub's **Security advisories** feature. Do not open a public issue for a vulnerability that could expose a deployed desktop or browser session.
