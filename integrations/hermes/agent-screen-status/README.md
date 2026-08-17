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

## Publisher contract

The plugin calls an operator-provided executable with exactly two arguments:

```text
publisher STATE TASK
```

Set its path using:

```bash
export AGENT_SCREEN_STATUS_PUBLISHER=/usr/local/bin/iris-screen-status
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
Environment=AGENT_SCREEN_STATUS_PLATFORMS=telegram,slack,discord
```

## Install

Ensure the publisher exists and is executable, then run:

```bash
AGENT_SCREEN_STATUS_PUBLISHER=/usr/local/bin/iris-screen-status \
  integrations/hermes/agent-screen-status/install.sh
```

The installer copies the plugin to `${HERMES_HOME:-$HOME/.hermes}/plugins/agent-screen-status`, enables it, and deliberately does not restart a live gateway. Restart the gateway only during a planned maintenance window, then send a real turn and verify `working` changes back to `idle` after completion.
