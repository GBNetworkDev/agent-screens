#!/usr/bin/env python3
import argparse
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description="Set the Agent Screens host name")
parser.add_argument("--hostname", default="agent-screens")
parser.add_argument("--fqdn", default="screens.example.com")
args = parser.parse_args()

hosts = Path("/etc/hosts")
lines = hosts.read_text().splitlines()
out = []
replaced = False
for line in lines:
    if line.split("#", 1)[0].strip().startswith("127.0.1.1"):
        if not replaced:
            out.append(f"127.0.1.1\t{args.fqdn}\t{args.hostname}")
            replaced = True
        continue
    out.append(line)
if not replaced:
    out.append(f"127.0.1.1\t{args.fqdn}\t{args.hostname}")
hosts.write_text("\n".join(out) + "\n")
Path("/etc/cloud/cloud.cfg.d/99-preserve-hostname.cfg").write_text("preserve_hostname: true\n")
subprocess.run(["hostnamectl", "set-hostname", args.hostname], check=True)
