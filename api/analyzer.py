import json
import re
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict
from pydantic import BaseModel, Field, field_validator, ConfigDict, ValidationError

EXCLUDED_DIRS = {'node_modules', '.git', '__pycache__',
                 'vendor', 'dist', 'build', '.next', 'target'}


class ShipzenConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    builder: Optional[str] = Field(
        None, pattern="^(dockerfile|buildpacks|railpack|go|maven|static|auto)$")
    port: Optional[int] = Field(None, ge=1, le=65535)
    build_args: Optional[Dict[str, str]] = None
    replicas: Optional[int] = Field(None, ge=1, le=20)
    health_check_path: Optional[str] = None

    @field_validator('health_check_path')
    @classmethod
    def validate_health_check_path(cls, v: str) -> str:
        if v and not v.startswith('/'):
            raise ValueError("health_check_path must start with /")
        return v


@dataclass
class DetectedService:
    name: str
    path: str
    type: str
    confidence: float
    framework: Optional[str] = None
    entrypoint: Optional[str] = None
    override_config: Optional[dict] = None
    port: Optional[int] = None
    package_manager: Optional[str] = None
    runtime_version: Optional[str] = None
    start_command: Optional[str] = None
    health_check_path: Optional[str] = None
    reasons: Optional[List[str]] = None


# Port each framework listens on unless told otherwise (ShipZen sets $PORT,
# which most of them honour; these are what to expect when they don't).
DEFAULT_PORTS = {"nextjs": 3000, "express": 3000, "vite": 8080, "fastapi": 8000, "django": 8000,
                 "flask": 5000, "go": 8080, "maven": 8080, "static": 8080, "dockerfile": 8080}
_LOCKFILES = [("bun.lockb", "bun"), ("bun.lock", "bun"), ("pnpm-lock.yaml", "pnpm"),
              ("yarn.lock", "yarn"), ("package-lock.json", "npm")]
_MAX_READ = 512 * 1024


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_READ:
            return ""
        return path.read_text(errors="replace")
    except Exception:
        return ""


def describe(current_path: Path, files: set, svc: "DetectedService") -> None:
    """Fill in port, package manager, runtime, start command, health path and reasons."""
    reasons = []
    if svc.type == "dockerfile":
        reasons.append("Dockerfile found: it is built as is.")
        m = re.search(r"^\s*EXPOSE\s+(\d{1,5})", _read(current_path / "Dockerfile"), re.M | re.I)
        if m and 1 <= int(m.group(1)) <= 65535:
            svc.port = int(m.group(1))
            reasons.append(f"Dockerfile EXPOSEs port {svc.port}.")
    if "package.json" in files:
        for lock, pm in _LOCKFILES:
            if lock in files:
                svc.package_manager = pm
                reasons.append(f"{lock} → installs with {pm}.")
                break
        else:
            svc.package_manager = "npm"
            reasons.append("No lockfile: installs with npm (commit a lockfile for repeatable builds).")
        try:
            pj = json.loads(_read(current_path / "package.json") or "{}")
        except ValueError:
            pj = {}
        engines = (pj.get("engines") or {}).get("node") if isinstance(pj.get("engines"), dict) else None
        nvmrc = _read(current_path / ".nvmrc").strip() if ".nvmrc" in files else ""
        if nvmrc or engines:
            svc.runtime_version = f"node {nvmrc or engines}"
            reasons.append(f"Node.js version from {'.nvmrc' if nvmrc else 'package.json engines'}: {nvmrc or engines}.")
        scripts = pj.get("scripts") if isinstance(pj.get("scripts"), dict) else {}
        if scripts.get("start"):
            svc.start_command = f"{svc.package_manager} start"
            reasons.append(f"Starts with the \"start\" script: {str(scripts['start'])[:80]}")
        elif scripts.get("build"):
            reasons.append("No start script but a build script: served as a static site after building.")
        else:
            reasons.append("No start script: add one that starts your server on $PORT.")
        if svc.framework:
            reasons.append(f"Framework: {svc.framework} (from package.json dependencies).")
    elif any(f in files for f in ("requirements.txt", "pyproject.toml", "manage.py")):
        for f, label in ((".python-version", ".python-version"), ("runtime.txt", "runtime.txt")):
            if f in files:
                v = _read(current_path / f).strip().splitlines()
                if v:
                    svc.runtime_version = v[0].replace("python-", "python ")[:40]
                    reasons.append(f"Python version from {label}: {v[0][:40]}.")
                    break
        if "Procfile" in files:
            svc.start_command = "Procfile"
            reasons.append("Starts with the Procfile's web process.")
        if svc.framework:
            reasons.append(f"Framework: {svc.framework}.")
    elif svc.type == "go":
        reasons.append("go.mod found: built as a Go binary.")
    elif svc.type == "maven":
        reasons.append("pom.xml found: built with Maven.")
    elif svc.type == "static":
        reasons.append("Only HTML: served as a static site.")
    if svc.port is None:
        svc.port = DEFAULT_PORTS.get(svc.framework or "", DEFAULT_PORTS.get(svc.type, 8080))
        reasons.append(f"Expected port {svc.port} (ShipZen also sets $PORT={svc.port}).")
    if svc.framework in ("fastapi", "django", "flask", "express", "nextjs"):
        svc.health_check_path = "/"
    if svc.override_config:
        reasons.append("shipzen.yaml found: its settings override what's detected.")
        if svc.override_config.get("port"):
            svc.port = svc.override_config["port"]
        if svc.override_config.get("health_check_path"):
            svc.health_check_path = svc.override_config["health_check_path"]
    svc.reasons = reasons


class RepoAnalyzer:
    def __init__(self, repo_path: str | Path, repo_name: str | None = None):
        self.repo_path = Path(repo_path)
        self._repo_name = repo_name or self.repo_path.name

    def analyze(self) -> List[DetectedService]:
        services = []
        base_path = self.repo_path.resolve()

        if not base_path.exists() or not base_path.is_dir():
            return services

        def walk_path(current_path: Path, _depth: int = 0):
            # M-4 Fix: Limit recursion depth to prevent runaway traversal of deep repo trees
            if _depth > 5:
                return

            if current_path != base_path:
                if current_path.name in EXCLUDED_DIRS or current_path.name.startswith('.'):
                    return

            rel_path = ""
            if current_path != base_path:
                rel_path = current_path.relative_to(base_path).as_posix()

            try:
                files = {p.name for p in current_path.iterdir() if p.is_file()}
            except Exception:
                return

            override_config = None
            if 'shipzen.yaml' in files:
                try:
                    with open(current_path / 'shipzen.yaml', 'r') as f:
                        raw_cfg = yaml.safe_load(f) or {}
                    parsed = ShipzenConfig(**raw_cfg)
                    override_config = parsed.model_dump(exclude_unset=True)
                except ValidationError as e:
                    unknown_keys = [err["loc"][0] for err in e.errors(
                    ) if err["type"] == "extra_forbidden"]
                    if unknown_keys:
                        raise ValueError(f"shipzen.yaml contains unknown fields: {unknown_keys}. "
                                         f"Allowed fields are: builder, port, build_args, replicas, health_check_path")
                    raise ValueError(f"shipzen.yaml validation error: {e}")
                except yaml.YAMLError as e:
                    raise ValueError(f"shipzen.yaml is not valid YAML: {e}")

            candidates = []

            # Dockerfile
            if 'Dockerfile' in files:
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name,
                    path=rel_path, type="dockerfile", confidence=1.0,
                    override_config=override_config
                ))

            # Buildpacks (Node/Python)
            if 'package.json' in files:
                framework = None
                try:
                    content = (current_path / "package.json").read_text()
                    if '"next"' in content:
                        framework = "nextjs"
                    elif '"vite"' in content:
                        framework = "vite"
                    elif '"express"' in content:
                        framework = "express"
                except Exception:
                    pass
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name,
                    path=rel_path, type="buildpacks", confidence=0.85,
                    framework=framework, override_config=override_config
                ))
            elif any(f in files for f in ['requirements.txt', 'pyproject.toml', 'manage.py']):
                framework = None
                if 'manage.py' in files:
                    framework = "django"
                req_path = current_path / "requirements.txt"
                if req_path.exists():
                    try:
                        content = req_path.read_text().lower()
                        if "fastapi" in content:
                            framework = "fastapi"
                        elif "flask" in content:
                            framework = "flask"
                    except Exception:
                        pass
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name,
                    path=rel_path, type="buildpacks", confidence=0.85,
                    framework=framework, override_config=override_config
                ))

            # Go
            if 'go.mod' in files and 'Dockerfile' not in files:
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name,
                    path=rel_path, type="go", confidence=0.90,
                    override_config=override_config
                ))

            # Java/Maven
            if 'pom.xml' in files and 'Dockerfile' not in files and 'go.mod' not in files:
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name,
                    path=rel_path, type="maven", confidence=0.88,
                    override_config=override_config
                ))

            # Static HTML
            if 'index.html' in files and 'package.json' not in files and not any(f in files for f in ['requirements.txt', 'pyproject.toml', 'manage.py', 'go.mod', 'pom.xml']):
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name,
                    path=rel_path, type="static", confidence=0.70,
                    framework="nginx", override_config=override_config
                ))

            # Railpack (Ruby/PHP)
            if any(f in files for f in ['composer.json', 'index.php', 'Gemfile']):
                candidates.append(DetectedService(
                    name=current_path.name or self._repo_name,
                    path=rel_path, type="railpack", confidence=0.85,
                    override_config=override_config
                ))

            if candidates:
                # Sort descending by confidence
                candidates.sort(key=lambda x: x.confidence, reverse=True)
                best_candidate = candidates[0]

                if override_config and override_config.get('builder'):
                    if override_config['builder'] != 'auto':
                        best_candidate.type = override_config['builder']
                        best_candidate.confidence = 1.0

                describe(current_path, files, best_candidate)
                services.append(best_candidate)

            # Recurse regardless of if we found a service here — monorepos can have nested services
            try:
                for d in current_path.iterdir():
                    if d.is_dir():
                        walk_path(d, _depth + 1)
            except Exception:
                pass

        walk_path(base_path)
        return services
