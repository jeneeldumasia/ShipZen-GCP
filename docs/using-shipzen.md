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

## 2. Deploy

1. Sign in at https://shipzen.jeneeldumasia.codes with GitHub.
2. **New project**: give it a name, the repository URL and the branch.
3. **Deploy**: pick the branch and port. You'll see the build log live.
4. When it says **Running**, the URL is on the deployment page. The pattern is
   `<8 chars>-<project>-shipzen.jeneeldumasia.codes`.

With the ShipZen GitHub App installed on the repository, a push to the project's
branch deploys automatically (pushes to other branches are ignored).

## 3. Configure

- **Environment variables and secrets**: project → Environment. Values are
  stored in Google Secret Manager, never in ShipZen's database, and reach your
  app as normal environment variables on the next deploy or restart.
- **Members**: project → Members. Owners and editors can deploy and change
  settings; viewers can only look.

## 4. Operate

| You want to | Do this |
|---|---|
| Go back to the previous version | **Rollback**: redeploys the last working release |
| Restart after changing env vars | **Restart** |
| Stop a build | **Cancel** |
| See logs, traffic, errors, crashes | Grafana → **ShipZen — Your app**, then pick your project |

## When it doesn't work

| Symptom | Check |
|---|---|
| Build fails with "No start command could be found" | Node: add a `start` script. Python: add a `Procfile`. |
| Build succeeds, app shows Offline | It isn't listening on `0.0.0.0:$PORT`, or it crashes at start (look at its logs) |
| App restarts over and over | Memory: the Grafana "How hard the app is working" chart near 100% |
| 502/503 from the URL | The app is still starting, or crashed; look at the Crashes panel |
