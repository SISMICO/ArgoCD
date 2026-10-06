#!/usr/bin/env python3
"""Seed private lab repositories without embedding credentials in Git remotes."""
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".state"
CONTEXT = "k3d-argocd-lab"
KUBECTL = ["kubectl", "--kubeconfig", str(STATE / "kubeconfig"), "--context", CONTEXT]
API = "http://127.0.0.1:13000/api/v1"
OWNER = "lab-admin"
READER = "lab-reader"
REPOSITORIES = ("platform-config", "workloads")


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def password_file(name):
    path = STATE / name
    if not path.exists():
        with path.open("x", encoding="utf-8") as handle:
            handle.write(secrets.token_urlsafe(32) + "\n")
    path.chmod(0o600)
    return path, path.read_text(encoding="utf-8").strip()


def api(method, path, username, password, body=None, missing_ok=False):
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    request = Request(
        API + path,
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        # Do not print response bodies: API errors may contain sensitive data.
        raise RuntimeError(f"Gitea {method} {path} returned HTTP {error.code}") from None


def ensure_user(username, password, admin=False):
    # Check Basic authentication first so reruns preserve existing accounts.
    try:
        api("GET", "/user", username, password)
        return
    except RuntimeError as error:
        if "HTTP 401" not in str(error):
            raise
    result = subprocess.run(
        KUBECTL + ["-n", "git", "exec", "deployment/gitea", "--", "gitea",
                   "--config", "/etc/gitea/app.ini", "--work-path", "/var/lib/gitea",
                   "admin", "user", "create", "--username", username,
                   "--password", password, "--email", f"{username}@homelab.invalid",
                   "--must-change-password=false"] + (["--admin"] if admin else []),
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"Cannot provision {username}. If the account already exists, restore its "
            "matching .state password file or reset it through the Gitea admin CLI."
        )
    api("GET", "/user", username, password)


def seed_repository(name, admin_password, git_env):
    repository = api("GET", f"/repos/{OWNER}/{name}", OWNER, admin_password, missing_ok=True)
    if repository is None:
        api("POST", "/user/repos", OWNER, admin_password,
            {"name": name, "private": True, "auto_init": False, "default_branch": "main"})
    api("PUT", f"/repos/{OWNER}/{name}/collaborators/{READER}", OWNER, admin_password,
        {"permission": "read"})
    destination = STATE / "repositories" / name
    remote = f"http://127.0.0.1:13000/{OWNER}/{name}.git"
    if not (destination / ".git").exists():
        existing = run(["git", "ls-remote", "--heads", remote], env=git_env,
                       capture_output=True, text=True).stdout.strip()
        if existing:
            raise RuntimeError(
                f"Remote {name} already has commits, but its local working copy is missing. "
                f"With make git-tunnel running, clone it to {destination}; then rerun make seed."
            )
        if destination.exists():
            raise RuntimeError(f"{destination} exists without .git; move it aside before seeding.")
        shutil.copytree(ROOT / "repositories" / name, destination)
        run(["git", "init", "--initial-branch=main", str(destination)], stdout=subprocess.DEVNULL)
        run(["git", "-C", str(destination), "config", "user.name", "Homelab Bootstrap"])
        run(["git", "-C", str(destination), "config", "user.email", "bootstrap@homelab.invalid"])
        run(["git", "-C", str(destination), "config", "commit.gpgsign", "false"])
        run(["git", "-C", str(destination), "add", "."])
        run(["git", "-C", str(destination), "commit", "-m", "Initialize GitOps configuration"],
            stdout=subprocess.DEVNULL)
        run(["git", "-C", str(destination), "remote", "add", "origin", remote])
    configured_remote = run(["git", "-C", str(destination), "remote", "get-url", "origin"],
                            capture_output=True, text=True).stdout.strip()
    if configured_remote != remote:
        raise RuntimeError(
            f"The {name} origin is not the expected lab tunnel URL. "
            f"Set origin to {remote}; keep production under a separate remote name."
        )
    # No force push. Divergent history requires an explicit merge by the user.
    run(["git", "-C", str(destination), "push", "--set-upstream", "origin", "main"], env=git_env)
    print(f"Seeded private repository: {name}", flush=True)


def repository_secret(name, reader_password):
    resource = {
        "apiVersion": "v1", "kind": "Secret",
        "metadata": {
            "name": f"repo-{name}", "namespace": "argocd",
            "labels": {"argocd.argoproj.io/secret-type": "repository"},
        },
        "type": "Opaque",
        "stringData": {
            "type": "git",
            "url": f"http://gitea.git.svc.cluster.local:3000/{OWNER}/{name}.git",
            "username": READER, "password": reader_password,
            "project": "platform" if name == "platform-config" else "demo",
        },
    }
    # Encoded data permits consistent server-side apply (stringData does not).
    resource["data"] = {key: base64.b64encode(value.encode()).decode()
                        for key, value in resource.pop("stringData").items()}
    run(KUBECTL + ["apply", "--server-side", "--field-manager=homelab-secrets", "-f", "-"],
        input=json.dumps(resource), text=True, stdout=subprocess.DEVNULL)


def main():
    os.umask(0o077)
    STATE.mkdir(exist_ok=True, mode=0o700)
    if not (STATE / "kubeconfig").is_file():
        raise RuntimeError("Run make cluster, make install-gitea and make install-argocd first.")
    run(KUBECTL + ["-n", "git", "rollout", "status", "deployment/gitea", "--timeout=600s"])
    admin_path, admin_password = password_file("gitea-admin-password")
    _, reader_password = password_file("gitea-reader-password")
    askpass = STATE / "git-askpass.py"
    askpass.write_text(
        '#!/usr/bin/env python3\n'
        'import os, pathlib, sys\n'
        'if "username" in sys.argv[1].lower():\n'
        '    print(os.environ["LAB_GIT_USERNAME"])\n'
        'else:\n'
        '    print(pathlib.Path(os.environ["LAB_GIT_PASSWORD_FILE"]).read_text().strip())\n',
        encoding="utf-8",
    )
    askpass.chmod(0o700)
    git_env = dict(os.environ, GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT="0",
                   LAB_GIT_USERNAME=OWNER, LAB_GIT_PASSWORD_FILE=str(admin_path),
                   GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="credential.helper", GIT_CONFIG_VALUE_0="")
    with (STATE / "gitea-port-forward.log").open("w") as log:
        tunnel = subprocess.Popen(
            KUBECTL + ["-n", "git", "port-forward", "--address", "127.0.0.1",
                       "service/gitea", "13000:3000"], stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(60):
                if tunnel.poll() is not None:
                    raise RuntimeError("Gitea tunnel stopped. Check .state/gitea-port-forward.log; port 13000 must be free.")
                try:
                    with urlopen("http://127.0.0.1:13000/api/healthz", timeout=2):
                        break
                except (URLError, TimeoutError):
                    time.sleep(1)
            else:
                raise RuntimeError("Gitea API did not become reachable in 60 seconds.")
            ensure_user(OWNER, admin_password, admin=True)
            ensure_user(READER, reader_password)
            for name in REPOSITORIES:
                seed_repository(name, admin_password, git_env)
                repository_secret(name, reader_password)
        finally:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait()
    print("Repositories configured. Working copies: .state/repositories/", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, URLError) as error:
        print(f"Seeding failed: {error}", file=sys.stderr)
        sys.exit(1)
