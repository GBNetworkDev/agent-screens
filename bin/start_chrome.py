#!/usr/bin/env python3
import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/agent-screen")
from agent_screen.runtime import (
    ScreenSpec,
    chrome_command,
    chrome_environment,
    read_session_environment,
    screen_id_from_display,
)


def main():
    if len(sys.argv) > 1:
        screen_id = int(sys.argv[1])
    else:
        screen_id = screen_id_from_display(os.environ.get("DISPLAY", ""))
    spec = ScreenSpec.from_id(screen_id)
    env = os.environ.copy()
    env.update(chrome_environment(spec))
    env_file = Path(spec.runtime_dir) / "session.env"
    env.update(read_session_environment(env_file))
    command = chrome_command(spec) + ["about:blank"]
    os.execvpe(command[0], command, env)


if __name__ == "__main__":
    main()
