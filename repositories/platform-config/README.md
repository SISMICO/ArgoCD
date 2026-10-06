# Platform configuration

This repository contains the Argo CD child Application definitions.
The root Application reads `argocd/lab` or `argocd/production`.

Only platform administrators should have write access: an Application definition
can delegate deployment privileges. AppProjects and namespaces are bootstrapped
separately by a Kubernetes administrator.

Lab child Applications sync automatically. Production Applications require an
explicit sync after the change has been reviewed. There are no cascading deletion
finalizers; deleting an Application leaves its deployed resources running.
