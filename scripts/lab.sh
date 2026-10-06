#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
cd "$ROOT_DIR"

cluster() {
  require docker
  require k3d
  require kubectl
  require python3
  docker info >/dev/null
  # JSON avoids guessing whether an existing cluster appears in table output.
  if k3d cluster list -o json | python3 -c 'import json,sys; sys.exit(0 if any(c["name"] == "argocd-lab" for c in json.load(sys.stdin)) else 1)'; then
    printf 'Using existing argocd-lab cluster.\n'
    k3d cluster start argocd-lab
  else
    k3d cluster create --config cluster/k3d.yaml
  fi
  k3d kubeconfig get argocd-lab > "$LAB_KUBECONFIG"
  chmod 600 "$LAB_KUBECONFIG"
  lab_kubectl wait --for=condition=Ready nodes --all --timeout=180s
  # K3s installs Traefik asynchronously after the nodes become Ready.
  for ((attempt=0; attempt<90; attempt++)); do
    if lab_kubectl -n kube-system get deployment traefik >/dev/null 2>&1; then
      lab_kubectl -n kube-system rollout status deployment/traefik --timeout=300s
      return
    fi
    sleep 2
  done
  printf 'Traefik did not appear. Inspect kube-system pods and HelmChart resources.\n' >&2
  exit 1
}

install_gitea() {
  require kubectl
  lab_kubectl apply -k kubernetes/gitea
  lab_kubectl -n git rollout status deployment/gitea --timeout=600s
}

install_argocd() {
  require kubectl
  lab_kubectl apply -f kubernetes/argocd/namespace.yaml
  # Server-side apply avoids oversized CRD annotation errors.
  lab_kubectl apply --server-side --field-manager=homelab-bootstrap -k kubernetes/argocd/overlays/lab
  lab_kubectl wait --for=condition=Established crd/applications.argoproj.io crd/appprojects.argoproj.io --timeout=120s
  lab_kubectl -n argocd rollout status deployment/argocd-redis --timeout=600s
  lab_kubectl -n argocd rollout status deployment/argocd-repo-server --timeout=600s
  lab_kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=600s
  lab_kubectl -n argocd rollout status deployment/argocd-server --timeout=600s
}

seed() {
  require python3
  require git
  require kubectl
  python3 scripts/seed-repositories.py
}

bootstrap() {
  require kubectl
  lab_kubectl -n argocd get secret repo-platform-config repo-workloads >/dev/null
  lab_kubectl apply -k bootstrap/lab
  python3 scripts/wait-apps.py
  printf '\nLab ready:\n  Argo CD: http://argocd.localhost:8080\n  Gitea:   http://gitea.localhost:8080\n  Web:     http://web.localhost:8080\n  API:     http://api.localhost:8080\n\nUse make credentials to display logins.\n'
}

status() {
  require kubectl
  lab_kubectl get nodes -o wide
  lab_kubectl -n argocd get applications
  lab_kubectl get pods -n argocd
  lab_kubectl get pods -n git
  lab_kubectl get deployments -n demo-web
  lab_kubectl get deployments -n demo-api
}

credentials() {
  require python3
  printf 'Gitea username: lab-admin\nGitea password: '
  cat "$STATE_DIR/gitea-admin-password"
  printf '\nArgo CD username: admin\nArgo CD initial password: '
  lab_kubectl -n argocd get secret argocd-initial-admin-secret -o 'jsonpath={.data.password}' |
    python3 -c 'import base64,sys; print(base64.b64decode(sys.stdin.read()).decode())'
}

case "${1:-help}" in
  up) cluster; install_gitea; install_argocd; seed; bootstrap ;;
  cluster) cluster ;;
  install-gitea) install_gitea ;;
  install-argocd) install_argocd ;;
  seed) seed ;;
  bootstrap) bootstrap ;;
  status) status ;;
  credentials) credentials ;;
  git-tunnel) lab_kubectl -n git port-forward --address 127.0.0.1 service/gitea 13000:3000 ;;
  down)
    require k3d
    # Deliberately no volume deletion beyond the explicitly named lab cluster.
    k3d cluster delete argocd-lab
    rm -f "$LAB_KUBECONFIG"
    printf 'Deleted argocd-lab. Local Git working copies and passwords remain in .state/.\n'
    ;;
  *) printf 'Unknown command. Run make help.\n' >&2; exit 2 ;;
esac

