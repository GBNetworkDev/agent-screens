# Hermes native Computer Use bridge

These scripts let a Hermes Agent host reach persistent `cua-driver` instances on an Agent Screens server through SSH. The checked-in examples are intentionally sanitized: there is no production hostname, IP address, SSH port, identity path, or credential.

## Components

- `cua-driver-remote-endpoint` — install on the Agent Screens server; selects one of four isolated Screen Unix sockets.
- `cua-driver-remote` — common SSH transport installed on the Hermes host.
- `cua-driver-screen1` through `cua-driver-screen4` — fixed-screen entry points for Hermes MCP.
- `rewrite_cua_manifest.py` — rewrites the remote manifest so Hermes launches the local wrapper rather than a path that exists only on the screen server.

The SSH transport is non-interactive and enforces `BatchMode`, `IdentitiesOnly`, and strict host-key checking. It does not expose CUA, VNC, CDP, or Websockify on a public listener.

## 1. Install the remote endpoint

On the Agent Screens server:

```bash
sudo install -o root -g root -m 0755 \
  integrations/hermes/cua-driver-remote-endpoint \
  /usr/local/sbin/cua-driver-remote-endpoint
```

Defaults:

- Screen 1 socket: `/home/agent/.cache/cua-driver/cua-driver.sock`
- Screen 2 socket: `/home/agent/.cache/cua-driver/cua-driver-screen2.sock`
- Screen 3 socket: `/home/agent/.cache/cua-driver/cua-driver-screen3.sock`
- Screen 4 socket: `/home/agent/.cache/cua-driver/cua-driver-screen4.sock`
- Driver: `/home/agent/.local/bin/cua-driver`
- Runtime user: `agent`

Override them through `AGENT_SCREEN_CUA_SOCKET_1` through `AGENT_SCREEN_CUA_SOCKET_4`, `AGENT_SCREEN_CUA_DRIVER`, `AGENT_SCREEN_CUA_USER`, or `AGENT_SCREEN_CUA_HOME` when your deployment differs.

## 2. Install the Hermes-side wrappers

On the Hermes host:

```bash
install -d -m 0700 "$HOME/.hermes/bin/agent-screens-cua"
install -m 0700 integrations/hermes/cua-driver-remote \
  integrations/hermes/cua-driver-screen1 \
  integrations/hermes/cua-driver-screen2 \
  integrations/hermes/cua-driver-screen3 \
  integrations/hermes/cua-driver-screen4 \
  "$HOME/.hermes/bin/agent-screens-cua/"
install -m 0700 integrations/hermes/rewrite_cua_manifest.py \
  "$HOME/.hermes/bin/agent-screens-cua/"
```

Set deployment-specific values in the Hermes service environment or its protected `.env` file. Do not commit the real values:

```dotenv
AGENT_SCREEN_SSH_HOST=screens.example.com
AGENT_SCREEN_SSH_USER=root
AGENT_SCREEN_SSH_PORT=22
AGENT_SCREEN_SSH_IDENTITY=/home/hermes/.ssh/agent-screens
AGENT_SCREEN_REMOTE_ENDPOINT=/usr/local/sbin/cua-driver-remote-endpoint
```

The SSH host key must already be present in the Hermes user's `known_hosts` file.

## 3. Register native MCP bridges

```bash
hermes mcp add cua_screen1 \
  --command "$HOME/.hermes/bin/agent-screens-cua/cua-driver-screen1" \
  --connect-timeout 30 --args mcp

hermes mcp add cua_screen2 \
  --command "$HOME/.hermes/bin/agent-screens-cua/cua-driver-screen2" \
  --connect-timeout 30 --args mcp

hermes mcp add cua_screen3 \
  --command "$HOME/.hermes/bin/agent-screens-cua/cua-driver-screen3" \
  --connect-timeout 30 --args mcp

hermes mcp add cua_screen4 \
  --command "$HOME/.hermes/bin/agent-screens-cua/cua-driver-screen4" \
  --connect-timeout 30 --args mcp
```

Enable all discovered tools when prompted, then verify each independent transport:

```bash
hermes mcp test cua_screen1
hermes mcp test cua_screen2
hermes mcp test cua_screen3
hermes mcp test cua_screen4
```

## 4. Optional built-in `computer_use` default

Point Hermes' built-in `computer_use` wrapper at one fixed screen, commonly Screen 2:

```dotenv
HERMES_CUA_DRIVER_CMD=/home/hermes/.hermes/bin/agent-screens-cua/cua-driver-screen2
```

Enable the toolset for the required messaging platform and restart the gateway:

```bash
hermes tools enable computer_use --platform telegram
hermes gateway restart
```

Start a new chat session after changing tool schemas. Direct MCP tools remain available as `cua_screen1` through `cua_screen4`, while built-in `computer_use` uses the selected default wrapper.

## 5. Specialist status ownership

Status ownership follows the actual worker, not only the orchestrator that received the user request.

When an orchestrator assigns work to a specialist profile or performs the work through that specialist's Screen, browser, or tools:

1. Publish the specialist's `working` state with a bounded, PII-safe task label **before the first specialist work action**.
2. The orchestrator may remain `working` concurrently while coordinating or validating the task.
3. On completion or interruption, publish the specialist's terminal state as `idle`, `waiting_approval`, or `error`, as applicable.
4. Do not leave a specialist at READY/idle while their assigned task is actively executing.
5. Ignore internal/background forks that are not the actual user-visible worker.

Apply this lifecycle independently to every specialist Screen. Status publishing must remain best-effort and must not block or change the outcome of the underlying work.

## Verification

```bash
HERMES_CUA_DRIVER_CMD="$HOME/.hermes/bin/agent-screens-cua/cua-driver-screen2" \
  hermes computer-use doctor
hermes mcp test cua_screen1
hermes mcp test cua_screen2
hermes mcp test cua_screen3
hermes mcp test cua_screen4
```

A healthy bridge reports the remote `cua-driver` version, an active MCP session, working X11/accessibility, and screen capture capability.

## Security notes

- Keep SSH keys and deployment values outside the repository.
- Keep all CUA sockets local to the Agent Screens server; transport them only through authenticated SSH.
- Do not disable strict host-key checking.
- Do not expose VNC, CDP, Websockify, or CUA sockets directly to the internet.
- Use a separate socket for every Screen so one bridge cannot silently control the wrong display.
