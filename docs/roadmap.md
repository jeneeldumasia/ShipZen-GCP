# Roadmap

What's open, most important first. Done items are deleted, not ticked:
`git log` and [operations/incidents.md](operations/incidents.md) are the history.

## Security
1. **Pin the build toolchain.** Build Nixpacks into a pinned builder image instead of `curl | bash` per build; pin Kaniko by digest.
2. **SSO for Grafana and ArgoCD** (GitHub OAuth) instead of admin passwords.

## Reliability
3. **Second alert channel** (Slack or email) in case the WhatsApp relay or CallMeBot is down.
4. **High availability** when it matters: nodes in more than one zone, Cloud SQL HA, Memorystore instead of in-cluster Redis.
5. **Keep metrics across rebuilds.** Remote-write Prometheus somewhere outside the cluster, or accept that history resets daily.

## Product
6. **Custom domains** for user apps.
7. **Opt-in app metrics.** Scrape `/metrics` only for apps that declare it (for example in `shipzen.yaml`), so apps without it don't raise "can't reach" alarms.
8. **One shipzen.yaml schema.** The worker accepts `buildContext`, but `/projects/analyze` rejects it as unknown; make them agree.
9. **Invite flow.** Today access is a fixed allowlist in the deployment manifests.

## Housekeeping
10. Clear out root-level leftovers: one-off test scripts (`test_k8s_*.py`, `test_db.py`), lint and test output files (`*_results.txt`), `commit_history_parsed.txt`, `dev_commits.txt`, `patch.yaml`, `karpenter-patch.yaml`, `update_aws_to_gcp.py`, and the AWS cleanup script.
11. Bring `.ai/` (context files for coding assistants) in line with these docs, or point it at them.
