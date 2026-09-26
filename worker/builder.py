from abc import ABC, abstractmethod
from typing import Dict, Any
import os
import json
import base64

import logging
from kubernetes import client


def get_ecr_credentials():
    # Deprecated: ECR authentication is now handled natively via IRSA
    # attached to the shipzen-builder-sa ServiceAccount.
    pass


logger = logging.getLogger('builder')


class Builder(ABC):
    @abstractmethod
    def detect(self, workspace_path: str) -> bool:
        """Return True if this builder can handle the repository."""

    @abstractmethod
    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        """Generate the Kubernetes Job manifest dictionary."""


class DockerfileBuilder(Builder):
    def detect(self, workspace_path: str) -> bool:
        return os.path.exists(os.path.join(workspace_path, "Dockerfile"))

    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        # CRIT-01 Fix: Use environment variables instead of f-string interpolation
        git_clone_env = [
            {"name": "GIT_REPO_URL", "value": repo_url},
            {"name": "GIT_BRANCH", "value": branch},
        ]
        if overrides.get("github_secret_name"):
            git_clone_env.append({"name": "GITHUB_TOKEN", "valueFrom": {"secretKeyRef": {"name": overrides["github_secret_name"], "key": "GITHUB_TOKEN"}}})
            clone_cmd = 'URL=$(echo "$GIT_REPO_URL" | sed "s|https://github.com/|https://x-access-token:${GITHUB_TOKEN}@github.com/|") && git clone --depth=1 --branch "$GIT_BRANCH" "$URL" /workspace'
        else:
            clone_cmd = 'git clone --depth=1 --branch "$GIT_BRANCH" "$GIT_REPO_URL" /workspace'

        # Safely extract base URI for cache
        base_uri = image_uri.split('@')[0]
        if ':' in base_uri.split('/')[-1]:
            base_uri = base_uri.rsplit(':', 1)[0]
        cache_uri = f"{base_uri}:cache"

        return {
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
                                    "--context=dir:///workspace",
                                    "--dockerfile=Dockerfile",
                                    f"--destination={image_uri}",
                                    "--cache=true",
                                    f"--cache-repo={cache_uri}"
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
                            {"name": "workspace", "emptyDir": {}}
                        ]
                    }
                }
            }
        }


class RailpackBuilder(Builder):
    def detect(self, workspace_path: str) -> bool:
        # Tier 3 fallback
        return os.path.exists(os.path.join(workspace_path, "Cargo.toml")) or os.path.exists(os.path.join(workspace_path, "bun.lockb"))

    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        # For now, Railpack uses Nixpacks as a placeholder until native compiler images are built
        b = NixpacksBuilder()
        return b.generate_job_manifest(deployment_id, repo_url, branch, image_uri, overrides)


class NixpacksBuilder(Builder):
    def detect(self, workspace_path: str) -> bool:
        return True  # Fallback for all other repos

    def generate_job_manifest(self, deployment_id: str, repo_url: str, branch: str, image_uri: str, overrides: dict) -> Dict[str, Any]:
        # CRIT-01 Fix: Use environment variables instead of f-string interpolation
        git_clone_env = [
            {"name": "GIT_REPO_URL", "value": repo_url},
            {"name": "GIT_BRANCH", "value": branch},
        ]
        if overrides.get("github_secret_name"):
            git_clone_env.append({"name": "GITHUB_TOKEN", "valueFrom": {"secretKeyRef": {"name": overrides["github_secret_name"], "key": "GITHUB_TOKEN"}}})
            clone_cmd = 'URL=$(echo "$GIT_REPO_URL" | sed "s|https://github.com/|https://x-access-token:${GITHUB_TOKEN}@github.com/|") && git clone --depth=1 --branch "$GIT_BRANCH" "$URL" /workspace'
        else:
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
  sed -i 's/"scripts": {/"scripts": { "start": "node server.cjs",/' package.json
fi
"""

        # Safely extract base URI handling digests and ports
        base_uri = image_uri.split('@')[0]
        if ':' in base_uri.split('/')[-1]:
            base_uri = base_uri.rsplit(':', 1)[0]
        cache_uri = f"{base_uri}:cache"

        nixpacks_args = ["build", "/workspace", "--out", "/workspace"]

        return {
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
                                "image": "ghcr.io/railwayapp/nixpacks:latest",
                                "command": ["/bin/sh", "-c", "curl -sSL https://nixpacks.com/install.sh | bash && /usr/local/bin/nixpacks \"$@\"", "--"],
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
                                    "--cache=true",
                                    f"--cache-repo={cache_uri}"
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
                            {"name": "workspace", "emptyDir": {}}
                        ]
                    }
                }
            }
        }
