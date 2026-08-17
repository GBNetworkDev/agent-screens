#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
DESTINATION="${HERMES_HOME}/plugins/agent-screen-status"
PUBLISHER="${AGENT_SCREEN_STATUS_PUBLISHER:-iris-screen-status}"

if ! command -v hermes >/dev/null 2>&1; then
  printf 'Hermes CLI is unavailable; install Hermes before this plugin.\n' >&2
  exit 1
fi

if ! command -v "${PUBLISHER}" >/dev/null 2>&1 && [[ ! -x "${PUBLISHER}" ]]; then
  printf 'Status publisher is unavailable: %s\n' "${PUBLISHER}" >&2
  printf 'Set AGENT_SCREEN_STATUS_PUBLISHER to an executable writer first.\n' >&2
  exit 1
fi

install -d -m 0755 "${DESTINATION}"
install -m 0644 "${SOURCE_DIR}/__init__.py" "${DESTINATION}/__init__.py"
install -m 0644 "${SOURCE_DIR}/plugin.yaml" "${DESTINATION}/plugin.yaml"
hermes plugins enable agent-screen-status

printf 'Installed agent-screen-status under %s\n' "${DESTINATION}"
printf 'Restart the Hermes gateway during a planned maintenance window.\n'
