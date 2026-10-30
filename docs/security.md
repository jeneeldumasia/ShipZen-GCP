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
- Builds run as `shipzen-builder-sa`, which can only push to the `shipzen-builds` registry. It cannot read Secret Manager, the build-log bucket or the platform images. The **Security Check** workflow verifies this from inside the cluster.
- Kaniko builds without a Docker daemon and without privileged mode (`allowPrivilegeEscalation: false`, `RuntimeDefault` seccomp).
- Registry credentials go to `crane` over stdin, and CI log output is passed through a redaction filter, so tokens don't reach logs or annotations.

**Platform**
- No long-lived keys: GitHub Actions uses Workload Identity Federation, pods use GKE Workload Identity, ArgoCD and the controller use a GitHub App.
- The platform services share `shipzen-platform-sa`, separate from the builder's identity (see [architecture.md](architecture.md#identities-and-permissions)).
- Kyverno policies are enforced cluster-wide. Exceptions are narrow and named: node-exporter and promtail need host access.
- The gateway's load balancer accepts traffic only from Cloudflare's IP ranges (`infra/system/gateway.yaml`), so the raw IP doesn't answer.
- `/metrics` refuses any request that came through Cloudflare. The API rate-limits per user, or per real client IP from `CF-Connecting-IP`.
- Tenant namespaces run Pod Security `restricted`, with quotas and no service-account token.
- Container images are scanned nightly by Trivy (**Container Security Scan**, fails on HIGH/CRITICAL).

## How to check

| Check | How |
|---|---|
| Builder identity is push-only | Run **Security Check** (Actions). All five probes must say PASS. |
| Raw gateway IP is closed | `curl -m 5 http://<gateway IP>/` should time out; the site should still load. |
| Nobody else can sign in | Sign in with another GitHub account: expect "Access denied". |
| Images are clean | Look at the latest **Container Security Scan** run. |

## Known gaps

1. **NetworkPolicies are not enforced.** The cluster has no network-policy provider (neither Dataplane V2 nor Calico), so `tenant-isolation` and `deny-tenant-ingress` do nothing. Tenant pods can currently reach each other and the platform. Fixing it needs two changes:
   - Enable enforcement. Dataplane V2 means recreating the cluster, which can ride on a normal destroy/redeploy.
   - Correct the tenant policy first. It admits pods labelled `app.kubernetes.io/name: envoy-gateway` in `shipzen-system`, but the gateway proxy runs in `envoy-gateway-system` as `app.kubernetes.io/name: envoy`. Enforcing it as written would cut every app off.
2. **Builds run as root inside the container** (`runAsUser: 0`; Kaniko needs it to unpack images). Nixpacks is installed with `curl | bash` at build time, not from a pinned image.
3. **Alerts reach nobody.** The Slack webhook in Secret Manager (`shipzen-alerts`) is a placeholder, so Alertmanager routing is switched off. Problems are only visible on the Grafana overview.
4. **One allowlisted user.** Fine for a personal platform; there is no self-service sign-up or invite flow.
5. **Grafana and ArgoCD use admin passwords.** There is no SSO in front of them.
