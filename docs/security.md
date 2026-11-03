# Security

What ShipZen protects, how, how to check it, and what is still open. Keep this
page honest: a control that exists in the repo but does not take effect belongs
under [Known gaps](#known-gaps), not under controls.

## What we are protecting against

| Threat | Why it matters here |
|---|---|
| A user's app or Dockerfile is malicious | ShipZen builds and runs code it did not write. A build must not be able to reach other tenants, platform secrets or platform images. |
| Someone who is not allowed signs in | Anyone with a GitHub account can reach the login page. |
| A project member does more than their role allows | Projects are shared between users with different roles. |
| Credentials leak | GitHub tokens, GCP tokens and the GitHub App key all pass through CI and logs. |
| Someone bypasses Cloudflare | Hitting the load balancer directly would skip Cloudflare's TLS and DDoS protection. |

## Controls in place

**Sign-in and roles**
- GitHub OAuth only. Both the UI (NextAuth `signIn` callback) and the API reject accounts not in `ALLOWED_GITHUB_USERS`.
- The API checks the user's GitHub token with GitHub on every request (cached briefly) and reports GitHub outages and rate limits as such, rather than "invalid token".
- Platform admins come only from `ADMIN_GITHUB_USERS` / `ADMIN_EMAILS`. The old "first user becomes admin" rule is gone.
- Per project: owners and editors can change things; viewers can only read. Write endpoints use `verify_project_write_access`.
- Every change is written to the append-only `audit_logs` table.

**Builds (untrusted code)**
- Each build is a single-use Job in its own namespace, `shipzen-build`, deleted afterwards.
- Build pods have **no Google identity** and can't reach the metadata server. The worker mints a 1-hour token for `shipzen-builder-sa`, which can push only to the `shipzen-staging` registry, and gives Kaniko just that. Kaniko reports the digest it pushed; the worker copies exactly that digest into `shipzen-builds` (which only the platform can write), and apps run **by digest**, so no build can swap another project's image. The shared remote layer cache is off, because any build could poison it. Each project's repository is checked against the user's own GitHub access and bound to the project, so nobody can build a private repository they can't read. **Security Check** verifies build pods have no identity.
- Kaniko builds without a Docker daemon and without privileged mode (`allowPrivilegeEscalation: false`, `RuntimeDefault` seccomp).
- Registry credentials go to `crane` over stdin, and CI log output is passed through a redaction filter, so tokens don't reach logs or annotations.

**Platform**
- No long-lived keys: GitHub Actions uses Workload Identity Federation, pods use GKE Workload Identity, ArgoCD and the controller use a GitHub App.
- The platform services share `shipzen-platform-sa`, separate from the builder's identity (see [architecture.md](architecture.md#identities-and-permissions)).
- Kyverno policies are enforced cluster-wide. Exceptions are narrow and named: node-exporter and promtail need host access.
- The gateway's load balancer accepts traffic only from Cloudflare's IP ranges (`infra/system/gateway.yaml`), so the raw IP doesn't answer.
- `/metrics` refuses any request that came through Cloudflare. The API rate-limits per user, or per real client IP from `CF-Connecting-IP`.
- Tenant namespaces run Pod Security `restricted`, with quotas and no service-account token.
- **Network isolation** (GKE Dataplane V2, which enforces NetworkPolicies):
  - tenants and build Jobs can reach DNS, their own pods and the public internet only, never other tenants, `shipzen-system`, monitoring, nodes, Cloud SQL or the metadata server;
  - `shipzen-system` accepts connections only from itself, the gateway and monitoring;
  - the API may only open DNS, Postgres, Redis, the metadata server and HTTPS.
- Container images are scanned by Trivy on demand (**Container Security Scan**, run manually; fails on HIGH/CRITICAL).

## How to check

| Check | How |
|---|---|
| Build pods have no Google identity | Run **Security Check** (Actions). Every identity probe must say PASS. |
| Network isolation holds | The same run starts a pod in a tenant namespace and one in `shipzen-build`; every connection must be blocked or allowed as expected (`scripts/netpolicy-probe.sh`). |
| Raw gateway IP is closed | `curl -m 5 http://<gateway IP>/` should time out; the site should still load. |
| Nobody else can sign in | Sign in with another GitHub account: expect "Access denied". |
| Images are clean | Look at the latest **Container Security Scan** run. |

## Known gaps

1. **Network isolation needs a cluster built after this change.** Dataplane V2 can only be chosen when a cluster is created, so a cluster created earlier has the policies but doesn't enforce them. **Security Check** fails until the next rebuild.
2. **Builds run as root inside the container** (`runAsUser: 0`; Kaniko needs it to unpack images). Nixpacks is installed with `curl | bash` at build time, not from a pinned image.
3. **Alerts have a single channel.** Everything goes to one Telegram chat (official Bot API). If Telegram is down, Alertmanager retries, but there is no second channel. The bot token can post to that chat, so keep it secret.
4. **One allowlisted user.** Fine for a personal platform; there is no self-service sign-up or invite flow.
5. **Grafana and ArgoCD use admin passwords.** There is no SSO in front of them.
