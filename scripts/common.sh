#!/usr/bin/env bash
# Sourced by lab.sh. Every Kubernetes operation has an explicit lab context.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT_DIR/.state"
LAB_KUBECONFIG="$STATE_DIR/kubeconfig"
LAB_CONTEXT=k3d-argocd-lab
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
umask 077

require() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Missing dependency: %s. See docs/INSTALLATION.md.\n' "$1" >&2
    exit 1
  }
}

lab_kubectl() {
  [[ -s "$LAB_KUBECONFIG" ]] || {
    printf 'Lab kubeconfig is missing. Run make cluster first.\n' >&2
    exit 1
  }
  kubectl --kubeconfig "$LAB_KUBECONFIG" --context "$LAB_CONTEXT" "$@"
}

