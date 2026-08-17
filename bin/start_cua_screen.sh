#!/usr/bin/env bash
set -euo pipefail

screen_id="${1:-1}"
case "$screen_id" in
  1|2|3|4) ;;
  *) echo "screen id must be between 1 and 4" >&2; exit 2 ;;
esac

export HOME=/home/agent
export PATH=/home/agent/.local/bin:/usr/local/bin:/usr/bin:/bin
export DISPLAY=":${screen_id}"
export XDG_RUNTIME_DIR="/tmp/agent-screen-runtime-${screen_id}"

for _ in $(seq 1 60); do
  session_file="${XDG_RUNTIME_DIR}/session.env"
  if [[ -r "$session_file" ]]; then
    session_display="$(sed -n 's/^DISPLAY=//p' "$session_file" | head -1)"
    DBUS_SESSION_BUS_ADDRESS="$(sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p' "$session_file" | head -1)"
    session_runtime="$(sed -n 's/^XDG_RUNTIME_DIR=//p' "$session_file" | head -1)"
    if [[ "$session_display" == "$DISPLAY" && -n "$DBUS_SESSION_BUS_ADDRESS" && "$session_runtime" == "$XDG_RUNTIME_DIR" ]]; then
      export DBUS_SESSION_BUS_ADDRESS
      break
    fi
  fi
  sleep 0.5
done

if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
  echo "could not discover desktop session for DISPLAY=${DISPLAY}" >&2
  exit 1
fi

gsettings set org.gnome.desktop.interface toolkit-accessibility true
dbus-send --session --print-reply --dest=org.a11y.Bus \
  /org/a11y/bus org.a11y.Bus.GetAddress >/dev/null

case "$screen_id" in
  1) socket=/home/agent/.cache/cua-driver/cua-driver.sock ;;
  2) socket=/home/agent/.cache/cua-driver/cua-driver-screen2.sock ;;
  3) socket=/home/agent/.cache/cua-driver/cua-driver-screen3.sock ;;
  4) socket=/home/agent/.cache/cua-driver/cua-driver-screen4.sock ;;
esac

exec /home/agent/.local/bin/cua-driver serve \
  --socket "$socket" \
  --permission-mode standard
