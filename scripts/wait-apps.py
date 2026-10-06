#!/usr/bin/env python3
"""Report reconciliation progress and stop if the demos never become healthy."""
import json
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent.parent
command = ["kubectl", "--kubeconfig", str(root / ".state/kubeconfig"),
           "--context", "k3d-argocd-lab", "-n", "argocd", "get", "applications", "-o", "json"]
deadline = time.monotonic() + 600
while time.monotonic() < deadline:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    applications = {item["metadata"]["name"]: item for item in json.loads(result.stdout)["items"]}
    ready = True
    for name in ("platform-root", "demo-web", "demo-api"):
        app = applications.get(name, {})
        status = app.get("status", {})
        sync = status.get("sync", {}).get("status", "Pending")
        health = status.get("health", {}).get("status", "Pending")
        conditions = "; ".join(c.get("message", "") for c in status.get("conditions", []))
        print(f"{name}: {sync} / {health}" + (f" ({conditions})" if conditions else ""), flush=True)
        ready = ready and sync == "Synced" and health == "Healthy"
    if ready:
        sys.exit(0)
    time.sleep(15)
print("Applications did not become Synced/Healthy in 10 minutes. See docs/INSTALLATION.md troubleshooting.",
      file=sys.stderr)
sys.exit(1)

