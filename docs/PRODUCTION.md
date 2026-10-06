# Repeat the Argo CD setup on a production cluster

Use the same Git repository separation, AppProjects and workload bases. The
production overlay is a starting configuration that needs your actual domains,
identity provider, ingress placement, credentials and capacity settings. Follow
this guide in a staging cluster before applying it to production.

The lab `make` targets always address `k3d-argocd-lab`. Production commands below
use a separately specified kubeconfig and context. Do not run `make up` as a
production installer.

## 1. Prepare real Kubernetes

Choose an existing managed Kubernetes cluster, a kubeadm cluster, or K3s on
separate machines. The application manifests use standard APIs; the supplied
production ingress uses Traefik v3's IngressRoute CRD.

For production K3s, use three server machines with embedded etcd and durable SSD
storage. Add workers as your capacity requires. Keep at least three schedulable
nodes for the Argo CD Redis HA placement rules; if control-plane nodes are
tainted, supply at least three eligible workers. Put the machines in separate
failure domains where possible. Three containers on one host do not provide
machine-level availability. See [K3s embedded-etcd HA](https://docs.k3s.io/datastore/ha-embedded).

The optional `cluster/k3s-production/` files provide server and agent config
examples. Provision machines with distinct hostnames, time synchronization,
appropriate firewall rules and non-overlapping cluster networks. Provide an API
load balancer forwarding TCP 6443 to the server nodes, with a stable DNS name.
Restrict node-to-node etcd and overlay networking to the private network; review
[K3s requirements](https://docs.k3s.io/installation/requirements).

On the **first server**, copy and customize `server-init.yaml.example` as
`/etc/rancher/k3s/config.yaml`:

```bash
sudo install -d -m 700 /etc/rancher/k3s
sudo install -m 600 server-init.yaml.example /etc/rancher/k3s/config.yaml
curl -fL https://get.k3s.io -o /tmp/install-k3s.sh
# Review the installer before executing it.
sudo env INSTALL_K3S_VERSION='v1.34.12+k3s1' sh /tmp/install-k3s.sh
sudo k3s kubectl get nodes
```

The copy command assumes you transferred the example to the server's current
directory. Pin and review the K3s release appropriate for your deployment date.
After the first server starts, point the API load balancer at it. Securely copy
`/var/lib/rancher/k3s/server/token` to `/etc/rancher/k3s/join-token` on each joining
machine with root ownership and mode 600. Do not place it in Git or print it into
shared logs.

On servers two and three, install the customized `server-join.yaml.example` as
`/etc/rancher/k3s/config.yaml`, then run the same pinned installer. Keep critical
settings identical across servers. Do not copy `cluster-init: true` to joining
servers. On workers, use `agent.yaml.example` and:

```bash
sudo env INSTALL_K3S_VERSION='v1.34.12+k3s1' sh /tmp/install-k3s.sh agent
```

Copy the first server's `/etc/rancher/k3s/k3s.yaml` securely to your administrator
machine, change its API URL from `127.0.0.1` to the load balancer DNS name, and
keep it mode 600. Rename its default context to a descriptive name such as
`production-admin`. Use a narrower identity for routine operations after bootstrap.

K3s enables Secret encryption with the server examples. For another Kubernetes
distribution, configure encryption at rest through its supported mechanism.

On your administrator machine, open a Bash terminal and set:

```bash
export PROD_KUBECONFIG=/secure/path/production-kubeconfig
export PROD_CONTEXT=production-admin

prod_kubectl() {
  kubectl --kubeconfig "$PROD_KUBECONFIG" --context "$PROD_CONTEXT" "$@"
}

prod_kubectl cluster-info
prod_kubectl get nodes -o wide
```

Keep this terminal for subsequent steps. Confirm the API endpoint and node list
before making changes. The HA overlay must be installed on a fresh namespace;
this guide does not perform an in-place migration from the lab's Redis deployment.

## 2. Prepare ingress, DNS and TLS

Install Traefik v3 with its Kubernetes CRD provider and a `websecure` entry point
on port 443. On an existing managed cluster, use your approved installation and
make its Service reachable through your load balancer. For K3s's bundled Traefik:

```bash
prod_kubectl apply -f cluster/k3s-production/traefik-ha.yaml
prod_kubectl -n kube-system rollout status deployment/traefik --timeout=600s
```

K3s's ServiceLB uses node ports 80/443; put a redundant external frontend in front
of eligible nodes or install your production LoadBalancer implementation. The
provided HelmChartConfig increases Traefik replicas and places them on different
nodes. It applies only to K3s's bundled chart; review your chart's values if you
install Traefik another way. See [K3s networking services](https://docs.k3s.io/networking/networking-services).

Create DNS records for Argo CD and the demo hosts pointing to the ingress address.
Obtain certificates from your organization's CA or your established certificate
controller. Do not depend on a default/self-signed Traefik certificate.

Replace these values in the local files **before rendering/applying**:

| Value | Files |
| --- | --- |
| `argocd.example.com` | Argo CD production `config.yaml` and `ingress.yaml` |
| `web.example.com`, `api.example.com` | Workload production `ingress.yaml` files |
| Git URLs under `git.example.com/platform/` | `bootstrap/production/` and platform repo production Applications |
| `sso.example.com/realms/platform` | Argo CD production `config.yaml` |
| `platform-admins`, `demo-deployers` | Argo CD production RBAC group mappings |
| Namespace `traefik` | Argo CD production `network-policy.yaml` and both workload production network policies |
| Namespace `monitoring` | Argo CD server metrics network-policy rule |

If using K3s's bundled Traefik, change the ingress namespace selectors from
`traefik` to **`kube-system`**. If using another controller, replace the Argo CD
IngressRoute with its supported UI/gRPC configuration and adjust the workload
IngressClass and annotations. Argo CD's
[ingress documentation](https://argo-cd.readthedocs.io/en/stable/operator-manual/ingress/)
explains the protocol requirements.

## 3. Move both repositories to durable Git hosting

Use GitHub, GitLab, a separately operated Gitea instance or another HTTPS Git
service reachable from the cluster. Create private `platform-config` and
`workloads` repositories. Production Gitea should have a supported database,
durable storage, TLS and a tested backup procedure; the lab's SQLite/local-path
Deployment is intended for experimentation.

For a fresh setup, copy the `repositories/platform-config/` and
`repositories/workloads/` templates into separate directories, initialize them
with `git init --initial-branch=main`, and push each to its production remote.
To retain lab history, push the working copies under `.state/repositories/` to
new remotes:

```bash
git -C .state/repositories/platform-config remote add production https://YOUR-GIT-HOST/YOUR-ORG/platform-config.git
git -C .state/repositories/workloads remote add production https://YOUR-GIT-HOST/YOUR-ORG/workloads.git
```

Update the **working copies'** production repo URLs, domains and network policies,
commit those changes, then:

```bash
git -C .state/repositories/platform-config push production main
git -C .state/repositories/workloads push production main
```

Also update `bootstrap/production/` locally; its URLs must exactly match both the
committed Application definitions and repository credential URLs. Commit the
installation/bootstrap configuration into your organization's controlled
infrastructure repository when adopting this setup.

Protect the production branch and require review. Restrict writes to the platform
repository to trusted administrators because it defines child Applications.
Workload authors need write access only to the workloads repository. Use separate
repositories or approved immutable revisions when different environments need
independent change histories; tracking `main` here demonstrates the workflow.

Create a dedicated Git identity for Argo CD, with read access only to these
repositories. Use scoped tokens or deploy keys. The credential helper supplied
here supports HTTPS tokens and one username. Adapt it to your provider if each
repository needs a different user or a GitHub App. Do not reuse the lab admin.

## 4. Register Argo CD with the identity provider

Create an OIDC client named `argocd`, with redirect URI:

```text
https://YOUR-ARGOCD-HOST/auth/callback
```

Match its client ID, issuer URL and requested scopes to `oidc.config` in the
production ConfigMap patch. Ensure the provider includes a `groups` claim with
values matching your RBAC mappings. Some providers use a custom group claim;
adjust `requestedScopes` and RBAC `scopes` accordingly. See
[Argo CD user management](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/).

Production disables the built-in admin account. Users in the administrative SSO
group get `role:admin`; demo deployers can read/sync demo Applications and read
logs. The default role grants no permissions. Test this with both groups and a
user outside them. Retain secured Kubernetes administrator access for recovery
if SSO is unavailable.

## 5. Install the production HA overlay

Create namespaces first:

```bash
prod_kubectl apply -f kubernetes/argocd/namespace.yaml
prod_kubectl apply -f bootstrap/production/namespaces.yaml
```

Provide valid certificate files from your CA or create equivalent Secrets through
your certificate controller. This manual example reads certificate/key files;
the generated Secret objects flow to kubectl through stdin:

```bash
prod_kubectl -n argocd create secret tls argocd-ingress-tls \
  --cert=/secure/certs/argocd.crt --key=/secure/certs/argocd.key \
  --dry-run=client -o yaml | prod_kubectl apply -f -
prod_kubectl -n demo-web create secret tls demo-web-tls \
  --cert=/secure/certs/web.crt --key=/secure/certs/web.key \
  --dry-run=client -o yaml | prod_kubectl apply -f -
prod_kubectl -n demo-api create secret tls demo-api-tls \
  --cert=/secure/certs/api.crt --key=/secure/certs/api.key \
  --dry-run=client -o yaml | prod_kubectl apply -f -
```

Render and review the HA installation, then apply it:

```bash
mkdir -p .state
kubectl kustomize kubernetes/argocd/overlays/production > .state/argocd-production.rendered.yaml
# Review the rendered file, especially cluster permissions and ingress/network policy.
prod_kubectl apply --server-side --field-manager=homelab-bootstrap \
  -k kubernetes/argocd/overlays/production
prod_kubectl wait --for=condition=Established \
  crd/applications.argoproj.io crd/appprojects.argoproj.io --timeout=120s
prod_kubectl -n argocd rollout status statefulset/argocd-redis-ha-server --timeout=600s
prod_kubectl -n argocd rollout status deployment/argocd-redis-ha-haproxy --timeout=600s
prod_kubectl -n argocd rollout status deployment/argocd-repo-server --timeout=600s
prod_kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=600s
prod_kubectl -n argocd rollout status deployment/argocd-server --timeout=600s
prod_kubectl -n argocd get pods -o wide
```

The production configuration references the official HA bundle, adds resource
budgets and disruption budgets for server/repo-server and Redis HA, and keeps
upstream HA placement. The Redis budget preserves two of its three pods during
voluntary maintenance. The controller remains a single replica for this single-cluster
example; it is restarted/rescheduled on failure, which pauses reconciliation.
Multiple controller replicas require a deliberate cluster sharding strategy.
See [Argo CD HA](https://argo-cd.readthedocs.io/en/stable/operator-manual/high_availability/).

Traefik terminates TLS; `server.insecure: true` allows HTTP/h2c only behind that
private frontend. The production patch replaces the upstream server's permissive
network policy with ingress from the chosen Traefik namespace, local Argo CD
pods, and the monitoring namespace on its metrics port. This requires a CNI that
enforces NetworkPolicy. Review other Argo CD component policies and restrict
egress to DNS, Kubernetes APIs, Git and the identity provider as your environment
allows. End-to-end encrypted pod traffic requires an additional backend TLS or
mesh design.

## 6. Install production credentials

Use your established secret manager to create the two repository Secrets with
the Argo CD `repository` label, and supply `oidc.clientSecret` in `argocd-secret`.
For a direct bootstrap, this helper prompts for two read-only Git tokens and the
OIDC client secret:

```bash
python3 scripts/configure-production-secrets.py \
  --kubeconfig "$PROD_KUBECONFIG" \
  --context "$PROD_CONTEXT" \
  --platform-url https://YOUR-GIT-HOST/YOUR-ORG/platform-config.git \
  --workloads-url https://YOUR-GIT-HOST/YOUR-ORG/workloads.git \
  --git-username YOUR-ARGOCD-GIT-USER
prod_kubectl -n argocd rollout restart deployment/argocd-server
prod_kubectl -n argocd rollout status deployment/argocd-server --timeout=600s
```

The helper sends Secrets through stdin and uses server-side apply to own just
the credentials it manages. It adds the OIDC data key without replacing the
other Argo CD secret keys. For ongoing rotation, use the same owner or transfer
ownership intentionally to your secret manager.

If your Git server has a private CA, add its CA to `argocd-tls-certs-cm` using
[Argo CD's trusted certificate configuration](https://argo-cd.readthedocs.io/en/stable/user-guide/private-repositories/).
Do not bypass certificate verification. SSH instead requires repository keys and
verified entries in `argocd-ssh-known-hosts-cm`.

## 7. Bootstrap and synchronize through review

```bash
prod_kubectl apply -k bootstrap/production
```

Open `https://YOUR-ARGOCD-HOST` and sign in with SSO. Alternatively, with the
matching Argo CD CLI:

```bash
argocd login YOUR-ARGOCD-HOST --sso --grpc-web
argocd repo list
argocd app diff platform-root
argocd app sync platform-root
argocd app get demo-web
argocd app diff demo-web
argocd app sync demo-web
argocd app wait demo-web --health --sync --timeout 600
argocd app diff demo-api
argocd app sync demo-api
argocd app wait demo-api --health --sync --timeout 600
```

The first root sync creates the two child Applications. Production has no
automated sync policy on the root or children. Future changes remain OutOfSync
until an authorized operator synchronizes them. Enable automation later only
after agreeing on review, branch protection and rollout policy.

The production demo overlays add two replicas, topology spreading, readiness
checks, quotas, disruption budgets, TLS ingress and network policies that allow
only ingress-controller traffic and no workload egress. Adapt them to real
application dependencies before using these policies for other services.

The supplied standard/HA bundle grants cluster-admin privileges to the controller.
The demo AppProject constrains Argo CD requests but does not remove those
Kubernetes privileges. For a constrained multi-tenant installation, design
namespace-scoped controller roles or dedicated Argo CD instances, review service
account permissions and explicitly manage any required cluster resources.

## 8. Verify behavior before promotion

Check the UI and CLI with an administrative user, a demo deployer and an
unassigned user. Confirm the deployer cannot edit the platform Application,
register arbitrary repos or target other namespaces.

```bash
prod_kubectl -n argocd get applications
prod_kubectl -n demo-web get deployment,pods,service,ingress,pdb,networkpolicy
prod_kubectl -n demo-api get deployment,pods,service,ingress,pdb,networkpolicy
curl --fail https://YOUR-WEB-HOST/
curl --fail https://YOUR-API-HOST/
```

Confirm certificate trust, approved repo URLs and successful read-only repo
authentication. Test a Git change, explicit sync and Git revert. In staging,
exercise pod replacement and one-node maintenance while checking availability
and quorum. Verify NetworkPolicy enforcement using your CNI's diagnostics.

Monitor Argo CD server, controller, repo-server and Redis health, application
sync errors, API/Git latency, CPU/memory pressure and certificate expiration.
Connect the metrics Services to your monitoring stack and tune resource budgets
from measured application count and reconciliation load.

## 9. Back up and recover

Back up both Git repositories through your Git provider. Back up Kubernetes
state and etcd through your cluster's supported process. For K3s embedded etcd:

```bash
# Run on a K3s server; copy resulting snapshots to independent protected storage.
sudo k3s etcd-snapshot save --name before-argocd-upgrade
```

Retain the server token securely alongside backups: it is needed to decrypt
bootstrap data during restore. Configure scheduled snapshots and durable off-host
storage, then practice restore in an isolated environment. Follow the
[K3s snapshot and restore guide](https://docs.k3s.io/cli/etcd-snapshot).

Export Argo CD configuration using the matching CLI and explicit context:

```bash
umask 077
argocd admin export --kubeconfig "$PROD_KUBECONFIG" --context "$PROD_CONTEXT" \
  --namespace argocd > .state/argocd-production-backup.yaml
```

Exports contain sensitive values. Encrypt and store them outside the cluster;
also retain the OIDC/Git secrets, CA configuration, TLS material and identity
provider configuration in your secure backup system. See
[Argo CD disaster recovery](https://argo-cd.readthedocs.io/en/stable/operator-manual/disaster_recovery/).

A recovery exercise should rebuild the cluster, reinstall the same approved Argo
CD version, restore its secrets/configuration, bootstrap AppProjects and the root
Application, and synchronize from Git. Workload data requires application-specific
backups in addition to these configuration exports.

## 10. Upgrade and roll back deliberately

Check current supported versions, security advisories and upgrade notes. Change
the pinned upstream URL in both Argo CD overlays, install the matching CLI, render
and inspect changes, and test the upgrade in staging. Back up configuration and
cluster state before production rollout. CRD/schema changes can make binary
downgrades unsafe, so follow the release's rollback guidance.

For workload rollback, revert the relevant Git commit, review the resulting
manifests and synchronize the Application. An Argo CD history rollback can be
overwritten by subsequent Git reconciliation; a Git revert records the lasting
desired state. Decide whether production image references should use approved
digests, and have CI update them through reviewed pull requests.
