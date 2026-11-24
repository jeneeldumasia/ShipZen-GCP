# Roadmap

What's open, most important first. Done items are deleted, not ticked:
`git log` and [operations/incidents.md](operations/incidents.md) are the history.

## Security
1. **Bake Nixpacks into a builder image** pinned by digest, so builds stop downloading it (it is already a pinned, checksummed release).
2. **Trim Kaniko's capabilities** to what it needs, verified with a test build of each builder type.

## Reliability
3. **Second alert channel** (email) in case Telegram or the relay is down.
4. **High availability** when it matters: nodes in more than one zone, Cloud SQL HA, Memorystore instead of in-cluster Redis.
5. **Keep metrics across rebuilds.** Remote-write Prometheus somewhere outside the cluster, or accept that history resets daily.

## Product
6. **Custom domains** for user apps.
7. **Opt-in app metrics.** Scrape `/metrics` only for apps that declare it (for example in `shipzen.yaml`), so apps without it don't raise "can't reach" alarms.
8. **Invitation emails.** Invitations work today, but the admin has to tell the person; send them a link.
