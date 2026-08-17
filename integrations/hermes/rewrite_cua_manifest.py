#!/usr/bin/env python3
import json
import os
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: rewrite_cua_manifest.py LOCAL_WRAPPER")

local_wrapper = os.path.abspath(sys.argv[1])
data = json.load(sys.stdin)
data["binary_path"] = local_wrapper
invocation = data.get("mcp_invocation")
if isinstance(invocation, dict):
    invocation["command"] = local_wrapper
json.dump(data, sys.stdout, separators=(",", ":"))
sys.stdout.write("\n")
