# ShipZen Project Structure Guide

ShipZen is designed to automatically build and deploy your applications directly from your Git repository. To ensure a successful deployment, your repository must be structured in a way that our builder engine can understand.

ShipZen supports two main deployment strategies: **Dockerfile Builds** and **Automated Buildpacks (Nixpacks)**.

---

## 1. Automated Buildpacks (Zero Configuration)

If you don't provide a `Dockerfile`, ShipZen uses **Nixpacks** to automatically detect your tech stack, install dependencies, and build your application. For this to work, your repository must have standard configuration files at the **root of your repository**.

### Node.js Applications (React, Next.js, Express, etc.)
Your repository must contain a `package.json` file at the root. 
Crucially, your `package.json` **must include a `start` script** that starts your web server.

**Example `package.json`:**
```json
{
  "name": "my-node-app",
  "version": "1.0.0",
  "scripts": {
    "build": "next build", 
    "start": "next start -p $PORT"
  },
  "dependencies": {
    "next": "latest",
    "react": "latest"
  }
}
```
*Note: Your application should listen on the port specified by the `PORT` environment variable.*

### Python Applications (FastAPI, Flask, Django)
Your repository must contain a `requirements.txt`, `Pipfile`, or `pyproject.toml` at the root. You should also provide a `Procfile` or a standard entry point to tell the builder how to start the app.

**Example `Procfile`:**
```text
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

### Go Applications
Include your `go.mod` and `go.sum` files at the root. The buildpack will automatically compile your code.

---

## 2. Dockerfile Deployments (Custom Configuration)

If your application requires complex system dependencies, a custom operating system, or a language not supported by buildpacks, you can include a `Dockerfile` at the root of your repository. 

ShipZen will detect the `Dockerfile` and build your image securely using Kaniko.

**Requirements:**
- The file must be named exactly `Dockerfile` and located at the root of the repository.
- Your container must bind to the `0.0.0.0` interface.
- Your container should listen on the port you configured during the ShipZen deployment process. 

**Example `Dockerfile`:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# Start the server listening on the dynamic PORT environment variable
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

---

## 3. Monorepos and Subdirectory Deployments

Currently, ShipZen builds your application from the **root of the repository**. If you have a monorepo or your frontend/backend code is nested in subdirectories (e.g., `/ui` or `/api`), you must route the build commands from the root directory.

If you are deploying a Node.js project nested in a `ui/` directory, create a `package.json` at the root of your repository that delegates the commands to your subdirectory:

**Root `package.json` for a Subdirectory App:**
```json
{
  "name": "monorepo-deploy-proxy",
  "scripts": {
    "postinstall": "cd ui && npm install",
    "build": "cd ui && npm run build",
    "start": "cd ui && npm run start"
  }
}
```
This ensures the builder engine detects a Node.js project, correctly installs the subdirectory dependencies, builds the sub-project, and knows how to start it.

---

## Troubleshooting

- **`Error: No start command could be found`**: This happens during a Buildpack build when no `start` script is found in your `package.json`, or no `Procfile` is found. Ensure these files exist at the root of your repository.
- **Port Binding Issues**: If your deployment succeeds but the health checks fail or the app is unreachable, verify that your web server binds to `0.0.0.0` (not `127.0.0.1` or `localhost`) and listens on the correct port.
