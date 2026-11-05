# Deploying an app on ShipZen

ShipZen builds your GitHub repository into a container and runs it at its own
HTTPS address. This page covers what your repository needs and what you can do
once it's running.

## 1. Make your repository buildable

ShipZen picks the build method automatically:

| Your repo has | ShipZen uses |
|---|---|
| A `Dockerfile` (at the root, or in the build folder you choose) | **Kaniko** builds exactly that Dockerfile |
| No Dockerfile | **Nixpacks** detects the language, writes a Dockerfile, and Kaniko builds it |

Whatever the method, **your app must listen on `0.0.0.0` and on the port in the
`PORT` environment variable** (8080 unless you choose another port when
deploying). This is the cause of most "deployed but offline" problems.

**Node.js**: `package.json` with a `start` script.
```json
{ "scripts": { "build": "next build", "start": "next start -p $PORT" } }
```

**Python**: `requirements.txt` (or `pyproject.toml` / `Pipfile`) plus a `Procfile`.
```text
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

**Go**: `go.mod` and `go.sum` at the root.

**Dockerfile**: any base image.
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

**Optional `shipzen.yaml`** at the repository root:
```yaml
buildContext: services/web      # build this subfolder instead of the root (monorepos)
port: 3000                      # overrides the port chosen in the UI
health_check_path: /healthz     # readiness check path
```

Older repositories may use `deployhub.yml` with the same fields; it is still read.

## 2. Deploy

1. Sign in at https://shipzen.jeneeldumasia.codes with GitHub.
2. **New project**: give it a name, the repository URL and the branch.
3. **Deploy**: pick the branch and port. You'll see the build log live.
4. When it says **Running**, the URL is on the deployment page. The pattern is
   `<8 chars>-<project>-shipzen.jeneeldumasia.codes`.

**Not sure what to fill in?** Press **Analyze** on the deploy page. ShipZen looks at
the repository without building it and lists each app it finds as a card. Each card shows:
- the framework, package manager and runtime version;
- the start command, port and health-check path;
- the reasons behind each guess, e.g. "pnpm-lock.yaml found" or "Next.js listens on 3000".

Pick a card to fill in the port and the **Build folder**. The build folder is for
monorepos: it's the subfolder that holds the app's Dockerfile or `package.json`.

**Automatic deploys.** With the ShipZen GitHub App installed on the repository, a
push to the project's branch deploys automatically; pushes to other branches are
ignored. A push deploy reuses the build folder of the last production deploy.

**Every deploy records its commit.** The deploy history shows the short SHA (linked
to GitHub), the commit message, the author, what triggered it (you, a push, a
rollback, a preview) and when.

**Give it a stable, free URL.** Each release gets its own URL, which changes on
every deploy. On the project page, under **Vanity URL**, pick a name such as
`myapp` and the project is reachable at `https://myapp-shipzen.jeneeldumasia.codes`.
That URL always points at the live release, survives redeploys and rollbacks,
and costs nothing. The card shows whether it's **Live**, still **Setting up** (DNS
can take a minute or two), or waiting for your next successful deploy. Names are
3–40 lowercase letters, digits and hyphens, unique across ShipZen. A few names are
reserved (`grafana`, `argocd`, `api`, …), and so is the release-URL shape: a hyphen
as the 9th character.

### Preview deploys for pull requests

When the GitHub App is installed, opening or updating a pull request against the
project's repository builds a **preview**:
- It's a separate release with its own URL, marked **Preview · PR #12** in the
  deploy list.
- ShipZen comments the link on the pull request and emails it to you.
- Previews never become the live release, and never touch production or the vanity URL.
- Each preview always runs one small instance.
- Closing or merging the pull request removes its preview.
- A project has at most 3 pull requests with previews at once. Each pull request
  builds one commit at a time.
- Pull requests from **forks are ignored**: their code isn't trusted to run on ShipZen.

## 3. Configure

- **Environment variables and secrets**: project → Environment. Values are
  stored in Google Secret Manager, never in ShipZen's database. Changes reach the
  app on the next deploy. Press **Apply now** to restart the live release with
  them straight away (no rebuild).
- **Members**: project → Members. Owners and editors can deploy and change
  settings; viewers can only look.
- **Scaling**: project → Scaling. Pick an instance size and how many instances to run:

  | Size | Guaranteed CPU / memory | Can burst to | Max instances |
  |---|---|---|---|
  | Small (default) | 0.1 vCPU / 128 MiB | 0.5 vCPU / 512 MiB | 5 |
  | Medium | 0.25 vCPU / 512 MiB | 1 vCPU / 1 GiB | 3 |
  | Large | 0.5 vCPU / 1 GiB | 1 vCPU / 2 GiB | 2 |

  If the maximum is above the minimum, ShipZen adds instances when CPU passes 70%
  and removes them when load drops. Scaling applies to the live release.
- **Email notifications**: the bell in the top bar. When it's on, you get an email
  at your GitHub-verified address when a deploy goes live, a deploy fails, an app
  goes down, or a preview is ready. This covers projects you own or edit. Turn it
  off any time.

## 4. Operate

| You want to | Do this |
|---|---|
| See what the app prints | Deployment page → **Logs**: the newest 500 lines of output, live and searchable |
| See how it's doing | Deployment page → **Metrics**: requests, 5xx errors, p95 response time, CPU, memory, instances and restarts (1 h / 6 h / 24 h) |
| Go back to the previous version | **Rollback**: instant within 10 minutes of a deploy (the old release is still running), otherwise it redeploys the last working image without rebuilding |
| Build the same commit again | **Redeploy** |
| Pick up changed env vars | **Apply now** on the Environment card |
| Restart the app | **Restart** |
| Stop a build | **Cancel** |
| Dig deeper | Grafana → **ShipZen — Your app** (admins) |

## When it doesn't work

When a build fails, ShipZen reads the build log and tells you why in plain words,
with a suggested fix. That appears on the deployment page and in the failure email.
Some failures have a safe fix, and ShipZen retries those **once by itself**. The
note on the deployment says what it changed:

| Failure | Automatic retry |
|---|---|
| `package-lock.json` out of sync with `package.json` | installs with `npm install` instead of `npm ci` |
| `pnpm-lock.yaml` out of date | `pnpm install --no-frozen-lockfile` |
| `ERR_OSSL_EVP_UNSUPPORTED` (older webpack on newer Node.js) | `NODE_OPTIONS=--openssl-legacy-provider` |
| JavaScript heap out of memory | a larger Node.js heap |

Fix the cause in your repository anyway; the retry is a stopgap.

| Symptom | Check |
|---|---|
| Build fails with "No start command could be found" | Node: add a `start` script. Python: add a `Procfile`. |
| "ShipZen couldn't tell what kind of app this is" | The app is in a subfolder: use **Analyze** and pick it, or add a Dockerfile |
| Build succeeds, app shows Offline | It isn't listening on `0.0.0.0:$PORT`, or it crashes at start (look at **Logs**) |
| App restarts over and over | Memory: check **Metrics**, then choose a bigger size under **Scaling** |
| 502/503 from the URL | The app is still starting, or crashed; look at **Logs** |
| Deploy refused: "Deploys are paused by a platform admin" | A platform-wide freeze (shown in the banner). Running apps are fine; deploy once it's lifted. |
| Deploy refused: "This project's owner is suspended" | Ask a platform admin |
