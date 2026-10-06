# Install and use the local lab

Run commands from this project's root directory. The scripts always use
`.state/kubeconfig` and the `k3d-argocd-lab` context. They do not rely on your
current Kubernetes context.

## 1. Prepare the host

Use Linux with Docker Engine, or macOS/Windows with Docker Desktop and a Linux
shell. On Windows, use WSL2. Start with 4 CPU cores, 8 GB of available RAM and
20 GB of disk space; image downloads and application load change these needs.

Install these dependencies:

| Tool | Requirement | Official instructions |
| --- | --- | --- |
| Docker | Running Linux container daemon, accessible by your user | [Docker installation](https://docs.docker.com/engine/install/) |
| k3d | v5.8.3 or newer compatible release | [k3d releases](https://github.com/k3d-io/k3d/releases/tag/v5.8.3) |
| kubectl | 1.34.x for this cluster | [kubectl installation](https://kubernetes.io/docs/tasks/tools/) |
| Git | 2.28 or newer (`git init --initial-branch`) | [Git installation](https://git-scm.com/downloads) |
| Python | 3.9 or newer; helpers use the standard library | [Python downloads](https://www.python.org/downloads/) |
| Make | GNU Make | Your operating system's package manager |

For Ubuntu/Debian, install basic tools with:

```bash
sudo apt-get update
sudo apt-get install -y git make python3 curl ca-certificates
```

Follow Docker's instructions above to install the daemon and configure your
user's access. For **Linux amd64**, these commands place the Kubernetes tools
inside the project (use the matching release assets for another architecture):

```bash
mkdir -p .state/bin
curl -fL --retry 3 -o .state/bin/k3d \
  https://github.com/k3d-io/k3d/releases/download/v5.8.3/k3d-linux-amd64
# Compare sha256sum .state/bin/k3d with the published release checksum before use.
curl -fL --retry 3 -o .state/bin/kubectl \
  https://dl.k8s.io/release/v1.34.12/bin/linux/amd64/kubectl
curl -fL --retry 3 -o .state/bin/kubectl.sha256 \
  https://dl.k8s.io/release/v1.34.12/bin/linux/amd64/kubectl.sha256
printf '%s  %s\n' "$(cat .state/bin/kubectl.sha256)" '.state/bin/kubectl' | sha256sum --check
chmod +x .state/bin/k3d .state/bin/kubectl
export PATH="$PWD/.state/bin:$PATH"
```

Re-export that PATH in subsequent terminals if you used project-local tools.
Confirm the tools and daemon:

```bash
docker info
k3d version
kubectl version --client
git --version
python3 --version
make --version
```

The host needs internet access to download K3s, Gitea, Argo CD and demo images,
and to fetch the pinned upstream Argo CD manifests. No GitHub account is required.

## 2. Create Kubernetes

```bash
make cluster
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab get nodes -o wide
```

Expect `k3d-argocd-lab-server-0` and `k3d-argocd-lab-agent-0` to be Ready.
K3s provides CoreDNS, Traefik, the ServiceLB implementation and the `local-path`
storage class. k3d adds a load balancer Docker container for port forwarding.

The API is exposed at `127.0.0.1:6445`, HTTP at `127.0.0.1:8080`, and HTTPS at
`127.0.0.1:8443`. The lab applications use HTTP. No process changes `/etc/hosts`.
If your system does not resolve these names, add this line to your hosts file:

```text
127.0.0.1 argocd.localhost gitea.localhost web.localhost api.localhost
```

The lab's node-local storage survives pod restarts and a stop/start of the same
cluster. It does not survive cluster deletion. Both nodes share one physical host.

## 3. Install the Git server

```bash
make install-gitea
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab -n git get pods,pvc,service,ingress
```

Gitea runs as UID/GID 1000 with two PVCs: repository/database data and persistent
configuration. It uses SQLite, disables self-registration and SSH, and locks the
installation wizard. The next step creates its users automatically.

Its browser URL is `http://gitea.localhost:8080`. Kubernetes clients use the
different internal address `http://gitea.git.svc.cluster.local:3000`. Inside a pod,
`localhost` refers to that pod, so Argo CD must use the internal Service address.

## 4. Install and configure Argo CD

```bash
make install-argocd
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab -n argocd get pods
```

The lab Kustomize overlay fetches the official versioned install manifest and
patches the UI URL, polling interval, resource budgets and HTTP configuration.
Server-side apply avoids the annotation size limit on Argo CD CRDs. See the
[official getting-started guide](https://argo-cd.readthedocs.io/en/stable/getting_started/).

To inspect the complete installation before applying it:

```bash
kubectl kustomize kubernetes/argocd/overlays/lab > .state/argocd-lab.rendered.yaml
```

The install includes controller, server, repository server, Redis, Dex,
ApplicationSet controller and notifications controller. The official full install
grants broad Kubernetes privileges to the controller; AppProjects restrict the
demo applications' permitted repositories, namespaces and kinds. AppProjects are
an Argo CD control, so production Kubernetes permissions need their own review.

## 5. Create and connect the Git repositories

```bash
make seed
```

This command starts a temporary loopback Gitea port forward and then:

1. Creates `lab-admin` and a separate `lab-reader` account with random passwords.
2. Creates the private `lab-admin/platform-config` and `lab-admin/workloads` repos.
3. Gives `lab-reader` read access to both repositories.
4. Copies each template into `.state/repositories/`, creates a `main` branch and pushes it.
5. Creates project-scoped Argo CD repository Secrets using the reader account.
6. Stops its temporary port forward.

Passwords are stored in `.state/gitea-admin-password` and
`.state/gitea-reader-password`, with restrictive permissions. `.state/` is ignored
by Git. The credential helper avoids passwords in Git remote URLs and command
output. Lab provisioning passes the new users' passwords to the in-pod Gitea CLI;
that bootstrap method belongs on a trusted local host. For production, use scoped
tokens or deploy keys and your secret manager.

Seeding again preserves working copies and users and uses ordinary pushes.
If remote history diverges, reconcile it with Git before retrying. If a remote
already has commits but its local working copy is missing, clone it instead of
replacing its history. Restore the password files if you retain the Gitea PVCs.

## 6. Bootstrap the applications

```bash
make bootstrap
make status
make credentials
```

The bootstrap creates two namespaces, restricts the otherwise permissive default
AppProject, and creates `platform` and `demo` AppProjects plus `platform-root`.
The root Application reads the platform repo and creates `demo-web` and `demo-api`.
Those Applications read workload overlays from the second repository. The helper
waits up to ten minutes for all three Applications to become Synced and Healthy.

Log into `http://argocd.localhost:8080` as `admin` with the displayed initial
password. Log into Gitea as `lab-admin`. Change the Argo CD admin password in the
UI's user settings; the initial password ceases to be useful after rotation.

Expected URLs:

| URL | Result |
| --- | --- |
| http://web.localhost:8080 | NGINX page explaining GitOps |
| http://api.localhost:8080 | Message from the HTTP Echo container |
| http://argocd.localhost:8080 | Three Applications, all Synced/Healthy |
| http://gitea.localhost:8080/lab-admin | Two private repositories after login |

For a fresh installation, `make up` runs steps 2–6 in sequence. Later `make up`
reruns keep local Git changes; they also reapply the lab installation configuration.

## 7. Deploy a change through Git

Keep a tunnel open in terminal A:

```bash
make git-tunnel
```

In terminal B, edit `.state/repositories/workloads/apps/web/base/index.html`, then:

```bash
git -C .state/repositories/workloads add apps/web/base/index.html
git -C .state/repositories/workloads commit -m "Update the demo page"
git -C .state/repositories/workloads push origin main
```

Git prompts for `lab-admin` and the password from `make credentials`. The seeded
remotes use the tunnel at `127.0.0.1:13000`; do not stop the tunnel until the push
finishes. Editing the initial `repositories/` templates after seeding does not
change the running applications.

Argo CD polls Git approximately every 60–75 seconds in this lab. The changed
ConfigMap gets a content hash, which updates the Deployment reference and starts
a rollout. Refresh the NGINX page after `demo-web` becomes Synced/Healthy. You can
use the Argo CD UI's Refresh action to ask for reconciliation sooner.

The API message is set by `args` in `apps/api/base/deployment.yaml`; edit and push
that file to exercise the other container. To scale an app, change `replicas` in
its Git manifest and push.

## 8. Practice drift correction and rollback

Scale a Deployment directly:

```bash
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab -n demo-web scale deployment/demo-web --replicas=3
```

The lab Applications have `selfHeal: true`; Argo CD returns the Deployment to its
Git-defined count. Changes should be committed to Git to persist.

To roll back a committed page change, keep the Git tunnel open and revert it:

```bash
git -C .state/repositories/workloads log --oneline -5
# Substitute the commit that introduced the change.
git -C .state/repositories/workloads revert <commit-sha>
git -C .state/repositories/workloads push origin main
```

Lab workload pruning is enabled: removing a managed resource from Git deletes it
after synchronization. The root Application does not auto-prune child Applications.
No Application has a cascading-deletion finalizer, so deleting an Application
leaves its workloads running. Removing an app requires reviewing its resources,
deleting them deliberately, and removing its Application definition from Git.

## 9. Optional Argo CD CLI

Install the matching CLI from the [v3.5.3 release](https://github.com/argoproj/argo-cd/releases/tag/v3.5.3).
For Linux amd64:

```bash
mkdir -p .state/bin
curl -fL --retry 3 -o .state/bin/argocd \
  https://github.com/argoproj/argo-cd/releases/download/v3.5.3/argocd-linux-amd64
# Verify release checksums/provenance before running the downloaded binary.
chmod +x .state/bin/argocd
export PATH="$PWD/.state/bin:$PATH"
argocd login argocd.localhost:8080 --username admin --plaintext --grpc-web
argocd app list
argocd app get demo-web
argocd app diff demo-web
```

`--plaintext` matches the lab's loopback HTTP endpoint. The standard Ingress
supports the CLI through gRPC-Web. Production uses TLS instead.

## 10. Troubleshoot

| Symptom | What to inspect |
| --- | --- |
| `make cluster` cannot connect to Docker | Start Docker and check your user's daemon access. |
| A host port is already in use | Free 6445/8080/8443, or change `cluster/k3d.yaml` before creating the cluster. Change configured URLs if you change 8080. |
| Browser gets a DNS error | Add the hosts-file entry from step 2; use the curl commands below to bypass DNS. |
| Browser gets 404 | Check the Host header, Traefik rollout and the corresponding Ingress. |
| Gitea is Pending | Inspect PVCs and `local-path` provisioning; check disk space and volume/node affinity. |
| Gitea reports permission denied | Inspect UID/GID 1000 volume access and fsGroup behavior in your storage driver. |
| Application has a repository error | Confirm Gitea is Ready, repository Secrets exist and internal URLs match. |
| Application says resource is not permitted | Review its AppProject whitelist and target namespace. |
| Images cannot pull / pods restart | Inspect events, registry access, CPU/memory limits and container logs. |
| `make seed` reports a tunnel error | Stop an existing `make git-tunnel`; port 13000 must be free while seeding. |
| Server-side apply reports an ownership conflict | Inspect the named field manager. Reconcile the prior installer with these manifests; force ownership only after reviewing the conflicting fields. |

Useful commands:

```bash
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab -n argocd describe application demo-web
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab -n argocd logs deployment/argocd-repo-server --tail=100
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab -n argocd logs statefulset/argocd-application-controller --tail=100
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab -n git logs deployment/gitea --tail=100
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab -n kube-system get pods
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab get events -A --sort-by=.lastTimestamp
curl --resolve web.localhost:8080:127.0.0.1 http://web.localhost:8080/
curl --resolve api.localhost:8080:127.0.0.1 http://api.localhost:8080/
```

Avoid copying Secret contents into logs or support tickets. To bypass ingress,
port-forward a specific Service on a free loopback port:

```bash
kubectl --kubeconfig .state/kubeconfig --context k3d-argocd-lab -n argocd port-forward --address 127.0.0.1 service/argocd-server 18080:80
# Open http://127.0.0.1:18080 while the command runs.
```

## 11. Stop, back up or remove the lab

Stop/start without deleting the nodes:

```bash
k3d cluster stop argocd-lab
k3d cluster start argocd-lab
```

Before deletion, push all desired commits and export both repositories while the
Git tunnel is open. Git bundles preserve committed history, but not uncommitted
files, Gitea users, issues or configuration:

```bash
mkdir -p .state/backups
git -C .state/repositories/workloads bundle create ../../backups/workloads.bundle --all
git -C .state/repositories/platform-config bundle create ../../backups/platform-config.bundle --all
```

Copy those bundles and needed uncommitted files outside this project for a durable
backup. For Gitea metadata, use its [backup and restore procedure](https://docs.gitea.com/administration/backup-and-restore/)
and retain both PVC contents. Keep backups containing credentials private.

```bash
make down
```

This deletes only `argocd-lab`, including its node-local Gitea data and Kubernetes
state. Local Git working copies, password files and bundles remain in `.state/`.
Rerun `make up` to rebuild from those working copies; user/issues metadata is
restored only from an actual Gitea backup.
