from abc import ABC, abstractmethod
from typing import Dict, Any
import os
import json
import base64

import logging
from kubernetes import client


logger = logging.getLogger('builder')

# Pinned build tools (supply chain): bump deliberately, with the new checksum.
NIXPACKS_VERSION = "v1.41.0"
NIXPACKS_URL = (f"https://github.com/railwayapp/nixpacks/releases/download/{NIXPACKS_VERSION}/"
                f"nixpacks-{NIXPACKS_VERSION}-x86_64-unknown-linux-musl.tar.gz")
NIXPACKS_SHA256 = "0f55de7874507b9cf7502113120bd96f2ab6979f78d10eaf2eb2ade9207b3af6"
NIXPACKS_RUNNER_IMAGE = "alpine:3.20.3"


def harden_build_job(job: dict, overrides: dict) -> dict:
    """Lock down a build Job (security finding C4). Builds run untrusted code.

    - No Kubernetes API token in the pod.
    - Kaniko's only registry credential is the per-build Docker config the
      worker creates (overrides["registry_secret_name"]): a 1-hour token that can
      push to shipzen-staging and nothing else. The pod has no Google identity of
      its own, and the build NetworkPolicy blocks the metadata server.
    """
    pod = job["spec"]["template"]["spec"]
    pod["automountServiceAccountToken"] = False
    # Own node pool, sandboxed with gVisor (security finding C5): a kernel or
    # container escape lands in the sandbox on a build-only node, not next to
    # the platform. BUILD_RUNTIME_CLASS="" turns gVisor off (e.g. if a tool
    # misbehaves under it) while keeping the separate pool.
    pod["nodeSelector"] = {"shipzen.jeneeldumasia.codes/node-type": "builder"}
    runtime_class = os.environ.get("BUILD_RUNTIME_CLASS", "gvisor")
    if runtime_class:
        pod["runtimeClassName"] = runtime_class
    secret = overrides.get("registry_secret_name")
    if secret:
        pod.setdefault("volumes", []).append({
            "name": "registry-auth",
            "secret": {"secretName": secret, "items": [{"key": "config.json", "path": "config.json"}]},
        })
        for c in pod["containers"]:
            if c["name"] == "kaniko":
                c.setdefault("volumeMounts", []).append(
                    {"name": "registry-auth", "mountPath": "/kaniko/.docker", "readOnly": True})
    return job


def git_auth_env_refs(secret_name):
    """Env for the clone container: git sends the token as a header, read from the
    per-build Secret. Unlike a token in the clone URL, this is never written to
    /workspace/.git/config, so a Dockerfile's `COPY . .` can't bake it into the image."""
    if not secret_name:
        return [{"name": "GIT_TERMINAL_PROMPT", "value": "0"}]
    return [
        {"name": "GIT_TERMINAL_PROMPT", "value": "0"},
        {"name": "GIT_CONFIG_COUNT", "value": "1"},
        {"name": "GIT_CONFIG_KEY_0", "value": "http.https://github.com/.extraheader"},
        {"name": "GIT_CONFIG_VALUE_0", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "GIT_AUTH_HEADER"}}},
    ]


class Builder(ABC):
    @abstractmethod
    def detect(self, workspace_path: str, overrides: dict = None) -> bool:
        """Return True if this builder can handle the repository."""

    @abstractmethod
    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        """Generate the Kubernetes Job manifest dictionary."""


class DockerfileBuilder(Builder):
    def detect(self, workspace_path: str, overrides: dict = None) -> bool:
        overrides = overrides or {}
        context_dir = overrides.get("buildContext", "").strip("/")
        return os.path.exists(os.path.join(workspace_path, context_dir, "Dockerfile"))

    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        # CRIT-01 Fix: Use environment variables instead of f-string interpolation
        git_clone_env = [
            {"name": "GIT_REPO_URL", "value": repo_url},
            {"name": "GIT_BRANCH", "value": branch},
        ]
        git_clone_env += git_auth_env_refs(overrides.get("github_secret_name"))
        clone_cmd = 'git clone --depth=1 --branch "$GIT_BRANCH" "$GIT_REPO_URL" /workspace'


        context_dir = overrides.get("buildContext", "").strip("/")
        kaniko_context = f"dir:///workspace/{context_dir}" if context_dir else "dir:///workspace"

        return harden_build_job({
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": f"build-{deployment_id[:8]}",
                "namespace": "shipzen-build",
                "labels": {
                    "shipzen.jeneeldumasia.codes/deployment": deployment_id,
                    "shipzen.jeneeldumasia.codes/tier": "dockerfile",
                    "shipzen.jeneeldumasia.codes/trace-id": str(overrides.get("trace_id", deployment_id))
                }
            },
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": 1800,  # 30 mins
                "template": {
                    "spec": {
                        "restartPolicy": "Never",
                        "serviceAccountName": "shipzen-builder-sa",
                        "tolerations": [
                            {"key": "shipzen.jeneeldumasia.codes/dedicated",
                                "operator": "Equal", "value": "builder", "effect": "NoSchedule"}
                        ],
                        "initContainers": [
                            {
                                "name": "git-clone",
                                "image": "alpine/git:2.43.0",
                                "command": ["sh", "-c"],
                                "args": [clone_cmd],
                                "env": git_clone_env,
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                                "resources": {
                                    "requests": {"cpu": "500m", "memory": "1Gi"},
                                    "limits": {"cpu": "1", "memory": "2Gi"}
                                },
                                "securityContext": {
                                    "runAsUser": 0,
                                    "allowPrivilegeEscalation": False,
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                }
                            }
                        ],
                        "containers": [
                            {
                                "name": "kaniko",
                                "image": "gcr.io/kaniko-project/executor:v1.23.2",
                                "args": [
                                    f"--context={kaniko_context}",
                                    "--dockerfile=Dockerfile",
                                    f"--destination={image_uri}",
                                    # No shared remote layer cache: every build could write it, so one
                                    # tenant could poison another's layers. The digest of what was
                                    # pushed goes to the termination message for the worker (C4).
                                    "--digest-file=/dev/termination-log"
                                ],
                                "resources": {
                                    "requests": {"cpu": "1", "memory": "2Gi"},
                                    "limits": {"cpu": "2", "memory": "4Gi"}
                                },
                                "volumeMounts": [
                                    {"name": "workspace", "mountPath": "/workspace"}
                                ],
                                "securityContext": {
                                    "runAsUser": 0,
                                    "allowPrivilegeEscalation": False,
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                }
                            }
                        ],
                        "volumes": [
                            {"name": "workspace", "emptyDir": {"sizeLimit": "10Gi"}}
                        ]
                    }
                }
            }
        }, overrides)





class NixpacksBuilder(Builder):
    def detect(self, workspace_path: str, overrides: dict = None) -> bool:
        return True  # Fallback for all other repos

    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        # CRIT-01 Fix: Use environment variables instead of f-string interpolation
        git_clone_env = [
            {"name": "GIT_REPO_URL", "value": repo_url},
            {"name": "GIT_BRANCH", "value": branch},
        ]
        git_clone_env += git_auth_env_refs(overrides.get("github_secret_name"))
        clone_cmd = 'git clone --depth=1 --branch "$GIT_BRANCH" "$GIT_REPO_URL" /workspace'

        setup_script = f"""
set -e
{clone_cmd}
chmod 777 /workspace
cd /workspace
"""
        if overrides.get("inject_server_js"):
            setup_script += """
cat << 'EOF' > server.cjs
const http = require('http');
const fs = require('fs');
const path = require('path');
const PORT = process.env.PORT || 8080;
const dirs = ['dist', 'build', 'out', 'public', '.'];
let DIR = __dirname;
for (const d of dirs) {
    if (fs.existsSync(path.join(__dirname, d, 'index.html'))) {
        DIR = path.join(__dirname, d);
        break;
    }
}
const mimeTypes = {
    '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
    '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpg',
    '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff': 'application/font-woff',
    '.woff2': 'application/font-woff2', '.ttf': 'application/font-ttf'
};
const server = http.createServer((req, res) => {
    let reqUrl = req.url.split('?')[0];
    let filePath = path.join(DIR, reqUrl === '/' ? 'index.html' : reqUrl);
    let extname = path.extname(filePath);
    if (!extname) {
        filePath = path.join(DIR, 'index.html');
        extname = '.html';
    }
    fs.readFile(filePath, (err, content) => {
        if (err) {
            if (err.code === 'ENOENT') {
                fs.readFile(path.join(DIR, 'index.html'), (err2, content2) => {
                    if (err2) { res.writeHead(500); res.end('Error'); }
                    else { res.writeHead(200, { 'Content-Type': 'text/html' }); res.end(content2, 'utf-8'); }
                });
            } else {
                res.writeHead(500); res.end(`Server Error: ${err.code}`);
            }
        } else {
            res.writeHead(200, { 'Content-Type': mimeTypes[extname] || 'application/octet-stream' });
            res.end(content, 'utf-8');
        }
    });
});
server.listen(PORT, () => console.log(`Static server listening on port ${PORT} serving ${DIR}`));
EOF
# Inject start script
if [ -f package.json ]; then
  apk add --no-cache python3
  python3 -c "import json; d=json.load(open('package.json')); d.setdefault('scripts', {})['start'] = 'node server.cjs'; json.dump(d, open('package.json','w'), indent=2)"
fi
"""


        context_dir = overrides.get("buildContext", "").strip("/")
        build_path = f"/workspace/{context_dir}" if context_dir else "/workspace"
        nixpacks_args = ["build", build_path, "--out", "/workspace"]
        # Build settings from an automatic retry (worker/failure_rules.py:
        # fixed values defined there, never from the repo or the log).
        for key, value in sorted((overrides.get("build_env") or {}).items()):
            nixpacks_args += ["--env", f"{key}={value}"]

        # A pinned Nixpacks release, checked against its SHA-256 before it runs
        # (it used to be `curl https://nixpacks.com/install.sh | bash` on every
        # build, in an image tagged :latest).
        nixpacks_cmd = (
            f"wget -q -O /tmp/nixpacks.tgz {NIXPACKS_URL} && "
            f"echo '{NIXPACKS_SHA256}  /tmp/nixpacks.tgz' | sha256sum -c - && "
            "tar -xzf /tmp/nixpacks.tgz -C /tmp nixpacks && "
            "/tmp/nixpacks \"$@\" && "
            "if [ -f /workspace/.nixpacks/build.sh ] && [ -f /workspace/.nixpacks/Dockerfile ]; then "
            "echo 'Injecting Nixpacks build-args into Dockerfile for Kaniko...' && "
            "grep -o -- '--build-arg [^ ]*' /workspace/.nixpacks/build.sh | while read -r flag arg; do "
            "if [ -n \"$arg\" ]; then "
            "if grep -q 'WORKDIR /app/' /workspace/.nixpacks/Dockerfile; then "
            "sed -i \"/WORKDIR \\/app\\//a ENV $arg\" /workspace/.nixpacks/Dockerfile; "
            "else echo \"ENV $arg\" >> /workspace/.nixpacks/Dockerfile; fi; "
            "fi; done; fi"
        )

        return harden_build_job({
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": f"build-{deployment_id[:8]}",
                "namespace": "shipzen-build",
                "labels": {
                    "shipzen.jeneeldumasia.codes/deployment": deployment_id,
                    "shipzen.jeneeldumasia.codes/tier": "buildpack",
                    "shipzen.jeneeldumasia.codes/trace-id": str(overrides.get("trace_id", deployment_id))
                }
            },
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": 1800,
                "ttlSecondsAfterFinished": 600,
                "template": {
                    "spec": {
                        "restartPolicy": "Never",
                        "serviceAccountName": "shipzen-builder-sa",
                        "tolerations": [
                            {"key": "shipzen.jeneeldumasia.codes/dedicated",
                                "operator": "Equal", "value": "builder", "effect": "NoSchedule"}
                        ],
                        "initContainers": [
                            {
                                "name": "setup",
                                "image": "alpine/git:2.43.0",
                                "command": ["sh", "-c", setup_script],
                                "env": git_clone_env,
                                "volumeMounts": [
                                    {"name": "workspace", "mountPath": "/workspace"}
                                ],
                                "resources": {
                                    "requests": {"cpu": "500m", "memory": "1Gi"},
                                    "limits": {"cpu": "1", "memory": "2Gi"}
                                },
                                "securityContext": {
                                    "runAsUser": 0,
                                    "allowPrivilegeEscalation": False,
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                }
                            },
                            {
                                "name": "nixpacks-generate",
                                "image": NIXPACKS_RUNNER_IMAGE,
                                "command": ["/bin/sh", "-c", nixpacks_cmd, "--"],
                                "args": nixpacks_args,
                                "resources": {
                                    "requests": {"cpu": "1", "memory": "2Gi"},
                                    "limits": {"cpu": "2", "memory": "4Gi"}
                                },
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                                "securityContext": {
                                    "runAsUser": 0,
                                    "allowPrivilegeEscalation": False,
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                }
                            },
                        ],
                        "containers": [
                            {
                                "name": "kaniko",
                                "image": "gcr.io/kaniko-project/executor:v1.23.2",
                                "args": [
                                    "--context=dir:///workspace",
                                    "--dockerfile=.nixpacks/Dockerfile",
                                    f"--destination={image_uri}",
                                    # No shared remote layer cache: every build could write it, so one
                                    # tenant could poison another's layers. The digest of what was
                                    # pushed goes to the termination message for the worker (C4).
                                    "--digest-file=/dev/termination-log"
                                ],
                                "resources": {
                                    "requests": {"cpu": "1", "memory": "2Gi"},
                                    "limits": {"cpu": "2", "memory": "4Gi"}
                                },
                                "volumeMounts": [
                                    {"name": "workspace", "mountPath": "/workspace"}
                                ],
                                "securityContext": {
                                    "runAsUser": 0,
                                    "allowPrivilegeEscalation": False,
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                }
                            }
                        ],
                        "volumes": [
                            {"name": "workspace", "emptyDir": {"sizeLimit": "10Gi"}}
                        ]
                    }
                }
            }
        }, overrides)
