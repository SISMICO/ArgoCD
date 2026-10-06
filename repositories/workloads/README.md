# Workloads

Two independent applications demonstrate GitOps with different container images:

- `apps/web`: unprivileged NGINX with a ConfigMap containing the page.
- `apps/api`: HashiCorp HTTP Echo.

Each application has a portable Kubernetes base and lab / production Kustomize
overlays. Commit changes here and push to `main`. Argo CD renders the selected
overlay. The production overlays add replicas, disruption budgets, TLS ingress
and network policy; customize domains and the ingress controller namespace first.

Do not commit credentials. CI should build, scan and publish application images,
then update image references in this repository through a reviewed pull request.
Argo CD deploys manifests; it does not build container images.
