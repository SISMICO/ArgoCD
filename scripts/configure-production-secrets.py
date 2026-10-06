#!/usr/bin/env python3
"""Create scoped repository credentials and add one OIDC key to argocd-secret."""
import argparse
import base64
from getpass import getpass
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--kubeconfig", required=True, type=Path)
parser.add_argument("--context", required=True)
parser.add_argument("--platform-url", required=True)
parser.add_argument("--workloads-url", required=True)
parser.add_argument("--git-username", required=True)
args = parser.parse_args()
if not args.kubeconfig.is_file():
    parser.error("The explicit production kubeconfig must exist.")
if args.context == "k3d-argocd-lab":
    parser.error("This command configures production credentials; use make seed for the lab.")
for url in (args.platform_url, args.workloads_url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        parser.error("Repository URLs must use HTTPS without embedded credentials.")
    if parsed.hostname == "example.com" or parsed.hostname.endswith(".example.com"):
        parser.error("Replace example.com with your real Git host.")

command = ["kubectl", "--kubeconfig", str(args.kubeconfig), "--context", args.context]
subprocess.run(command + ["-n", "argocd", "get", "secret", "argocd-secret"],
               check=True, stdout=subprocess.DEVNULL)


def apply_secret(name, data, labels=None):
    resource = {
        "apiVersion": "v1", "kind": "Secret", "type": "Opaque",
        "metadata": {"name": name, "namespace": "argocd"},
        "data": {key: base64.b64encode(value.encode()).decode() for key, value in data.items()},
    }
    if labels:
        resource["metadata"]["labels"] = labels
    subprocess.run(command + ["apply", "--server-side", "--field-manager=production-credentials", "-f", "-"],
                   input=json.dumps(resource), text=True, check=True)


# Prompt for all values before making changes.
platform_token = getpass("Read-only token for platform-config: ")
workloads_token = getpass("Read-only token for workloads: ")
oidc_secret = getpass("OIDC client secret: ")
if not all((platform_token, workloads_token, oidc_secret)):
    parser.error("All three secrets must be nonempty.")
for name, url, project, token in (
    ("platform-config", args.platform_url, "platform", platform_token),
    ("workloads", args.workloads_url, "demo", workloads_token),
):
    apply_secret(f"repo-{name}",
                 {"type": "git", "url": url, "username": args.git_username,
                  "password": token, "project": project},
                 {"argocd.argoproj.io/secret-type": "repository"})
# Server-side apply owns only this data key; preserve existing signing/password keys.
apply_secret("argocd-secret", {"oidc.clientSecret": oidc_secret})
print("Production repository credentials and OIDC secret configured.")

