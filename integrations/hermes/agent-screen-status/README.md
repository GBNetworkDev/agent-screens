# Hermes Agent Screen status plugin

This optional Hermes user plugin maps top-level agent lifecycle events to the bounded JSON status consumed by the Agent Screens command header.

## Behavior

- `pre_llm_call` publishes `working`.
- `post_llm_call` never finalizes a turn; authoritative `on_session_end`
  publishes the terminal `idle` or `error` state.
- Interrupted turns publish `error`.
- Approval requests publish `waiting_approval`.
- Approval events are correlated to an already tracked `turn_id`; unrelated
  background approvals cannot change owner-visible status.
- Denial, timeout, notification failure, and unknown approval outcomes fail
  closed to `error` instead of reporting that work continued.
- Concurrent top-level turns do not publish `idle` early.
- Background review and subagent forks with `parent_session_id` are ignored.
- Raw prompts and responses are never published; task labels come from a small bounded vocabulary.
- `pre_tool_call` maps exact `cua_screen2`, `cua_screen3`, and `cua_screen4`
  tool prefixes to their specialist Screen and publishes `working` before the
  first specialist action in a tracked owner-visible turn.
- Successful `post_tool_call` events do not publish `idle`; the specialist
  remains working across a multi-tool task until authoritative `on_session_end`.
- Specialist tool failure, interruption, approval wait, denial, and overlapping
  turns are independently tracked without copying tool arguments or results.
- Screen 1 remains owned by the top-level Iris lifecycle; ordinary terminal and
  unrelated tools do not activate a specialist.

## Publisher contract

The plugin calls an operator-provided executable with exactly two arguments:

```text
publisher STATE TASK
```

Set its path using:

```bash
export AGENT_SCREEN_STATUS_PUBLISHER=/usr/local/bin/iris-screen-status
export AGENT_SCREEN_STATUS_PUBLISHER_2=/usr/local/bin/tara-screen-status
export AGENT_SCREEN_STATUS_PUBLISHER_3=/usr/local/bin/atlas-screen-status
export AGENT_SCREEN_STATUS_PUBLISHER_4=/usr/local/bin/mira-screen-status
```

The executable may call `bin/update_screen_status.py` locally or transport the update to a remote Agent Screens host. Keep hostnames, ports, SSH identity paths, tokens, and credentials outside this repository.

Optionally restrict lifecycle platforms with a comma-separated list:

```bash
export AGENT_SCREEN_STATUS_PLATFORMS=telegram,slack,discord
```

For a systemd-managed gateway, persist the publisher path in the service
environment rather than relying on a transient shell export:

```bash
systemctl --user edit hermes-gateway.service
```

Add the following drop-in, then reload systemd during the planned gateway
restart:

```ini
[Service]
Environment=AGENT_SCREEN_STATUS_PUBLISHER=/usr/local/bin/iris-screen-status
Environment=AGENT_SCREEN_STATUS_PUBLISHER_2=/usr/local/bin/tara-screen-status
Environment=AGENT_SCREEN_STATUS_PUBLISHER_3=/usr/local/bin/atlas-screen-status
Environment=AGENT_SCREEN_STATUS_PUBLISHER_4=/usr/local/bin/mira-screen-status
Environment=AGENT_SCREEN_STATUS_PLATFORMS=telegram,slack,discord
```

## Install

Ensure the publisher exists and is executable, then run:

```bash
AGENT_SCREEN_STATUS_PUBLISHER=/usr/local/bin/iris-screen-status \
  integrations/hermes/agent-screen-status/install.sh
```

The installer copies the plugin to `${HERMES_HOME:-$HOME/.hermes}/plugins/agent-screen-status`, enables it, and deliberately does not restart a live gateway. Restart the gateway only during a planned maintenance window, then send a real turn and verify `working` changes back to `idle` after completion.
