# Roadmap

What's open, most important first. Done items are deleted, not ticked:
`git log` and [operations/incidents.md](operations/incidents.md) are the history.

## Security
1. **Pin the build toolchain.** Build Nixpacks into a pinned builder image instead of `curl | bash` per build; pin Kaniko by digest.
2. **SSO for Grafana and ArgoCD** (GitHub OAuth) instead of admin passwords.

## Reliability
3. **Second alert channel** in case Telegram or the relay is down. Deploy emails already go through Resend; platform alerts could use it too.
4. **High availability** when it matters: nodes in more than one zone, Cloud SQL HA, Memorystore instead of in-cluster Redis.
5. **Keep metrics across rebuilds.** Remote-write Prometheus somewhere outside the cluster, or accept that history resets daily.

## Product
6. **Custom domains** for user apps.
7. **Opt-in app metrics.** Scrape `/metrics` only for apps that declare it (for example in `shipzen.yaml`), so apps without it don't raise "can't reach" alarms.
8. **One shipzen.yaml schema.** The worker and the deploy form use `shipzen_common/repo_config.py` (`port`, `health_check_path`, `buildContext`). `api/analyzer.py` has its own model, which rejects `buildContext` and accepts fields nothing uses (`builder`, `build_args`, `replicas`). Make the analyzer use `repo_config` too.
9. **Invite flow.** Today access is a fixed allowlist in the deployment manifests.
10. **Suspension that stops apps.** Suspending a user blocks sign-in and deploys, but their running apps keep serving.
11. **More automatic build fixes.** Add rules to `worker/failure_rules.py` as new failure patterns show up in build notes.

## Housekeeping
12. Clear out leftovers still in Git: the old root `migrations/` folder (the schema now lives in `api/migrations/`), `ShipZen_Comprehensive_Study_Guide.pdf`, `scripts/cleanup-aws-resources.sh` and the one-off PowerShell fix scripts.
13. Tidy `docs/history.md` phases 1–10: they still carry AWS-era wording (Amazon registries, `data.aws_*` lookups).
