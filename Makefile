SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help up cluster install-gitea install-argocd seed bootstrap status credentials git-tunnel down
help:
	@printf '%s\n' \
	  'make up              Create the cluster, install services, seed Git, and deploy demos' \
	  'make cluster         Create only the two-node K3s cluster' \
	  'make install-gitea   Install the local Git server' \
	  'make install-argocd  Install and configure Argo CD' \
	  'make seed            Create private Git repositories and Argo CD repository Secrets' \
	  'make bootstrap       Apply projects and root Application; wait for demo deployment' \
	  'make status          Show lab resources' \
	  'make credentials     Display local lab login credentials' \
	  'make git-tunnel      Forward Gitea to 127.0.0.1:13000 for Git operations' \
	  'make down            DELETE the lab cluster and its in-cluster data'

up cluster install-gitea install-argocd seed bootstrap status credentials git-tunnel down:
	@bash scripts/lab.sh $@

