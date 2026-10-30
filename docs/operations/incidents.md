# Incidents and fixes

Problems ShipZen has hit and what fixed them, newest first. Use it to recognise a
problem you have seen before. Entries from the AWS era (before the move to GCP)
are kept where the lesson still applies.

## October 2026

| Problem | Cause | Fix |
|---|---|---|
| Tenant and build pods could reach the API, Redis, Grafana, Cloud SQL and the metadata server | No NetworkPolicy enforcement on the cluster; the tenant policy also named the wrong gateway | Dataplane V2, corrected policies, and a probe in **Security Check** |
| Template changes never reached existing apps (a removed metrics check kept alerting for smoke-test) | `tenant.yaml` was written only while a project was being provisioned | The controller re-renders it for Ready projects about every 20 min (#21) |
| Slack alerts never sent | The Slack webhook was a placeholder, so the operator rejected the whole routing config. Deploy workflows also reset the secret on every run. | Routing disabled until a real webhook exists. Workflows now create the placeholder only if missing (#20, this change). |
| Grafana showed 33 dashboards, mostly "No data" | Stock dashboards switched off with the wrong Helm key; ShipZen dashboards queried names that don't exist; Loki not connected | Four generated dashboards, Loki datasource, Envoy scraping (#19) |
| Permanent critical alerts for scheduler, controller-manager, kube-proxy | GKE manages these, so they can't be scraped | Scraping disabled (#19) |
| Users signed out with "invalid token" when GitHub was slow or rate-limiting | Every non-200 from GitHub was reported as 401 | Only GitHub's 401 becomes 401; rate limits and outages are 503 with `Retry-After` (#18) |
| Gateway IP answered directly, bypassing Cloudflare | Load balancer open to the internet | `loadBalancerSourceRanges` limited to Cloudflare |
| Build pods could read platform secrets and images | Builders shared the platform's service account | Separate push-only `shipzen-builder-sa`; **Security Check** proves it (#15) |
| A GCP access token appeared in a build log and a CI annotation | `crane auth` received it as an argument | Token passed on stdin; CI output redacted |
| Pods kept running `:latest` after merges | The ArgoCD image override dropped the tag | Build and Push pins `sha-<commit>` in `infra/kustomization.yaml` |
| ArgoCD stuck retrying an old sync after a rollout | A sync with the new probes but the old image | Build and Push terminates a stuck operation and starts a fresh sync (#14) |
| Old namespaces reappeared in ArgoCD | Tenant folders outlived their projects; no cascade delete | ApplicationSet finalizer and controller orphan cleanup |
| Apply failed with dozens of `409 already exists` | State from a killed run never reached HCP Terraform | `scripts/adopt-orphaned-resources.sh` imports them before plan |
| Superseded releases shown as CrashLoopBackOff | Releases scaled to 0 were checked like live ones | Skip the crash check when replicas is 0 |

## Earlier

| Problem | Cause | Fix |
|---|---|---|
| Rate limiting blocked everyone at once | Limiter keyed on the gateway's IP | Key on user, or the real client IP from Cloudflare |
| Demoted admin kept access for 5 min | Cached user object included the role | Role changes invalidate the cache |
| Race creating users on first login | Implicit commits in the pool | Explicit commit/rollback around the upsert |
| Hardcoded admin emails in migrations | Bootstrapping shortcut | `ADMIN_EMAILS` / `ADMIN_GITHUB_USERS` |
| Local stub auth could fail open | Environment-name checks | Explicit `ENABLE_LOCAL_STUB_AUTH=true` opt-in |
| Whole build namespace exempt from Kyverno | Over-broad exclusion | Narrow PolicyExceptions only |
| Webhooks deployed the wrong project or branch | Projects had no repo/branch of their own | `repo_url` and `branch` per project; webhooks match both |
| Builds always used `main` | Worker dropped the `branch` field | Passed through end to end |
| Build lost if a worker crashed mid-build | Un-acked messages never reclaimed | `XAUTOCLAIM` recovery and a dead-letter queue |
| Env vars never reached apps | API and controller used different secret paths | One secret per project id |
| Registry pull token expired after 12 h | Static token | Workload Identity, and an ESO generator for pulls |
| Controller couldn't update existing apps (409) | Create-only logic | Patch when the object exists |
| API ran out of DB connections | No pool | Pool with a bounded wait (503 instead of hanging) |
| GitHub Actions couldn't authenticate after the repo rename | Workload Identity condition named the old repo | Update the condition whenever the repo is renamed |
| HCP Terraform "no valid credentials" | Workspace in remote execution mode | Local execution mode |
| Stale Cloudflare records after teardown | Nothing deleted them | Teardown deletes them |
| node-exporter blocked by Kyverno | Needs host namespaces and hostPath | Named PolicyException |
| Envoy Gateway resources rejected | Old API group | `gateway.envoyproxy.io/v1alpha1` |
| `terraform init` failing on a 500 | Unused third-party kubectl provider | Provider removed |
