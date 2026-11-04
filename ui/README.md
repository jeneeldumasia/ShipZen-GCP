# ShipZen UI

The ShipZen web app: Next.js 16 (App Router), NextAuth v5 with GitHub sign-in,
Tailwind. It runs as `shipzen-ui` in the cluster, behind the same hostname as the
API (`https://shipzen.jeneeldumasia.codes`, API under `/api/v1`).

## How it talks to the API

- **Server components** call the API directly with the signed-in user's GitHub
  token from `auth()` (`src/lib/api.ts`).
- **Browser code** calls the same paths on `/api/proxy/...`
  (`src/app/api/proxy/[...path]/route.ts`), which adds the token on the server.
  The token never reaches browser JavaScript, and the proxy refuses cross-site writes.
- **Live build logs** use a WebSocket authenticated with a one-time ticket
  (`POST /ws-tickets`), not the token.

## Where things are

| Path | What |
|---|---|
| `src/app/projects/` | Projects, deploy form (Analyze, build folder), deployment page (build log, Logs, Metrics), env vars, scaling, vanity URL |
| `src/app/admin/` | Admin dashboard (session cost, announcement and deploy freeze), users (roles, suspension), projects, deployments, audit log |
| `src/components/` | Navigation (with the email-notifications bell), platform banner, command palette, shared UI |
| `src/lib/api.ts` | Typed API client used by both server and browser code |
| `src/auth.ts` | NextAuth config; refuses logins not in `ALLOWED_GITHUB_USERS` |

## Develop

```bash
npm install
npm run dev          # http://localhost:3000, expects the API on http://localhost:8000
npx tsc --noEmit     # type check (CI builds the image with `next build`)
```

Start the API locally with `docker compose -f docker-compose.local.yml up` from
the repository root (stub sign-in, no Kubernetes). See
[../docs/operations/setup.md](../docs/operations/setup.md#local-development).
