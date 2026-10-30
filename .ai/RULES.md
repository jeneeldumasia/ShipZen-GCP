# Engineering & Agent Rules

## Git Workflow
- **Commit After Fixes**: After fixing a bug or completing a change, you must automatically stage and commit the changes on behalf of the user. (Note: As per PROJECT_CONTEXT.md, commit locally but do NOT push).

## Infrastructure & Kubernetes Lessons
- **Kyverno PolicyExceptions**: When writing a `PolicyException` for Kyverno to bypass rules on Pod-controllers (DaemonSets, Deployments), the webhook evaluates against the auto-generated rules (`autogen-`). To ensure it matches both the controller and the pods, you must specify BOTH the original rule name (e.g. `host-namespaces`) AND the auto-generated name (`autogen-host-namespaces`) in the `ruleNames` array. Also, ensure you target the exact APIGroup in `Kinds` (e.g. `apps/v1/DaemonSet`).
- **Terraform local-exec pipelines**: When using `local-exec` to pipe `cat <<EOF` into `kubectl apply -f -`, be careful not to chain commands (like `gcloud container clusters get-credentials`) in the same pipe sequence if they do not consume `stdin`. Run configuration commands on a separate line before piping the YAML to `kubectl`.
- **ExternalDNS and Manual DNS Records**: `external-dns` is configured with `--policy=upsert-only` and a TXT registry. It will **refuse to update** any existing Cloudflare records that were created manually (because they lack the companion TXT ownership record). To ensure `external-dns` manages the record, you must either delete the manual record via Cloudflare API so `external-dns` can recreate it, or manually add the TXT ownership record. Never create DNS records manually for dynamically provisioned infrastructure like LoadBalancers.

## Documentation Workflow
- **Always Update Docs**: Anytime you modify source code, architecture, or configurations, you must automatically update the relevant documentation (e.g. `README.md`, ADRs, architecture diagrams, inline docstrings) in the same session to reflect the changes. Do not wait for the user to prompt you to update the docs.

## Lessons from October 2026
- **NetworkPolicies need an enforcer.** Without Dataplane V2 (or Calico) GKE accepts them and ignores them. Check selectors against real pod labels: the Envoy proxy is `app.kubernetes.io/name: envoy` in `envoy-gateway-system`, not `envoy-gateway` in `shipzen-system`.
- **Workload Identity behind an egress policy** needs 169.254.169.254/32:80 and 169.254.169.252/32:988 allowed.
- **gcloud label filters**: `labels.x:*` does not match labels with empty values (GKE's `goog-gke-volume`); use `labels.x=''`.
- **Never pass tokens as command arguments** (they end up in logs); use stdin. The repo is public: anything echoed into an annotation is public.
- **Workflow logs aren't downloadable from Claude's sandbox**: surface results as `::notice`/`::error` annotations (see cluster-report.yaml, scripts/ci-run.sh).
- **Workflows must not overwrite user-set secrets**: create placeholders only when missing.
- **Kube-prometheus-stack chart keys**: stock dashboards are `grafana.defaultDashboardsEnabled`; Grafana folders from annotations need `sidecar.dashboards.provider.foldersFromFilesStructure=true`.
- **Before assuming a fix worked, measure it** (Cluster Report, Security Check, Grafana API). Example: the disk-cleanup filter looked right but matched nothing, which only showed when the report counted the in-use disks.

## Documentation Map
- Humans: README.md → docs/ (using-shipzen, architecture, security, decisions, roadmap, operations/*).
- Assistants: this folder. Keep CURRENT_STATE.md and TASKS.md current; put durable explanations in docs/, not here.
