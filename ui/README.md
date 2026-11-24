# ShipZen UI

The ShipZen dashboard: GitHub sign-in, projects, deployments with live build logs,
environment variables, scaling, vanity URLs and the admin console.

Built with Next.js 16 (App Router), NextAuth v5 (GitHub OAuth) and Tailwind CSS.
Pages call the ShipZen API through a server-side proxy (`src/app/api/proxy`) using
the signed-in user's GitHub token.

## Run locally

```bash
npm install
npm run dev          # http://localhost:3000
```

Without a GitHub OAuth app, set `ENABLE_LOCAL_STUB_AUTH=true` to sign in with a
local stub user. Running `docker compose -f docker-compose.local.yml up` from the
repo root starts the API it talks to.

## Configuration

| Variable | Purpose |
|---|---|
| `API_URL` | Where the API is reachable from the UI server |
| `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` | GitHub OAuth app (`SHIPZEN_`-prefixed names also work) |
| `AUTH_SECRET` | NextAuth session secret |
| `AUTH_URL` | Public URL of the UI |
| `ALLOWED_GITHUB_USERS` | Comma-separated GitHub logins allowed to sign in (fails closed when empty) |
| `ALLOW_OPEN_SIGNUP` | `true` lets anyone sign in (keep this off in production) |
| `NEXT_PUBLIC_APP_DOMAIN` | Base domain for app URLs |
| `NEXT_PUBLIC_GITHUB_APP_SLUG` | GitHub App to install for push-to-deploy |
| `ENABLE_LOCAL_STUB_AUTH` | `true` for local development without GitHub |

## Scripts

| Command | |
|---|---|
| `npm run dev` | Development server with hot reload |
| `npm run build` | Production build |
| `npm run start` | Serve the production build |
| `npm run lint` | ESLint |

In production the UI runs as the `shipzen-ui` Deployment (`infra/ui/`). Images are
built by the **Build and Push Docker Images** workflow and rolled out through ArgoCD.
