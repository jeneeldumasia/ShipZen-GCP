/**
 * ShipZen API client.
 *
 * Server code (server components) calls the API directly with the user's
 * GitHub token from auth(). Browser code calls the same paths on
 * /api/proxy, the UI's own server, which adds the token there: the token never
 * reaches browser JavaScript (security finding H1).
 */

export function getBaseUrl(): string {
  if (typeof window !== "undefined") {
    if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
      return "http://localhost:8000";
    } else if (window.location.hostname === "shipzen.jeneeldumasia.codes") {
      return "https://shipzen.jeneeldumasia.codes/api/v1";
    } else {
      return "https://api." + window.location.hostname;
    }
  } else {
    if (process.env.KUBERNETES_SERVICE_HOST) {
      return "http://shipzen-api.shipzen-system.svc.cluster.local:80";
    } else {
      return process.env.API_URL ?? "http://localhost:8000";
    }
  }
}

export function getWsBaseUrl(): string {
  return getBaseUrl().replace(/^http/, "ws");
}

// Browser calls go through the same-origin proxy route.
const BASE = typeof window !== "undefined" ? "/api/proxy" : getBaseUrl();

async function serverToken(): Promise<string | undefined> {
  if (typeof window !== "undefined") return undefined; // the proxy adds it
  const { auth } = await import("@/auth");
  const session = await auth();
  return (session as { accessToken?: string })?.accessToken;
}

/** One-time ticket a browser sends as its first WebSocket message. */
export async function wsTicket(): Promise<string> {
  const res = await fetch("/api/proxy/ws-tickets", { method: "POST" });
  if (!res.ok) throw new Error(`Could not open a live connection (HTTP ${res.status})`);
  return (await res.json()).ticket;
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = await serverToken();

  const headers: Record<string, string> = { 
    "Content-Type": "application/json", 
    ...(options.headers as Record<string, string>) 
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      message = body.detail ?? body.message ?? message;
    } catch {}
    throw new Error(message);
  }

  // 204 No Content or empty body
  const text = await res.text();
  return text ? JSON.parse(text) : ({} as T);
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Project {
  id: string;
  name: string;
  namespace: string;
  status: "Provisioning" | "Ready" | "Terminating";
  created_at: string;
  deleted_at: string | null;
  webhook_secret?: string;
  deployments_count?: number;
  subdomain?: string | null;
  instance_size?: InstanceSize;
  min_instances?: number;
  max_instances?: number;
}

export type InstanceSize = "small" | "medium" | "large";

export interface Deployment {
  deployment_id: string;
  project_id: string;
  repo_url: string;
  image_uri: string;
  replicas: number;
  port: number;
  state: "Queued" | "Building" | "Deploying" | "Verifying" | "Running" | "Failed" | "Retry" | "DLQ" | "Superseded";
  updated_at: string;
  last_error: string | null;
  created_at?: string;
  branch?: string | null;
  commit_sha?: string | null;
  commit_message?: string | null;
  commit_author?: string | null;
  commit_url?: string | null;
  triggered_by?: string | null;
  kind?: "production" | "preview";
  pr_number?: number | null;
  build_context?: string | null;
  notes?: { type: "diagnosis" | "auto_fix"; code: string; message: string; suggestion?: string }[];
}

export interface DetectedService {
  name: string;
  path: string;
  type: string;
  confidence: number;
  framework?: string | null;
  port?: number | null;
  package_manager?: string | null;
  runtime_version?: string | null;
  start_command?: string | null;
  health_check_path?: string | null;
  reasons?: string[] | null;
}

export interface Build {
  build_id: string;
  deployment_id: string;
  s3_log_uri: string | null;
  status: "Success" | "Failed" | "In Progress";
  started_at: string;
  completed_at: string | null;
}

export interface AuditLog {
  id: number;
  project_id: string;
  user_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: Record<string, unknown>;
  timestamp: string;
}

// ── Projects ──────────────────────────────────────────────────────────────────

export interface RuntimeLogLine {
  ts: number; // nanoseconds
  pod: string;
  line: string;
}

export interface MetricsResponse {
  range: string;
  step: number;
  start: number;
  end: number;
  series: Record<string, [number, number | null][]>;
}

export const api = {
  analyze: (repo_url: string, branch: string) =>
    request<{ services: DetectedService[] }>("/projects/analyze", {
      method: "POST",
      body: JSON.stringify({ repo_url, branch }),
    }),
  users: {
    setNotifications: (email: boolean) =>
      request<{ email_notifications: boolean }>("/users/me/notifications", {
        method: "PUT",
        body: JSON.stringify({ email }),
      }),
  },
  github: {
    branches: (repoUrl: string) =>
      request<{ branches: string[]; total: number }>(
        `/github/branches?repo_url=${encodeURIComponent(repoUrl)}`
      ),
  },

  webhooks: {
    install: (projectId: string, repoUrl: string) =>
      request<{ message: string }>(`/projects/${projectId}/webhooks/install`, {
        method: "POST",
        body: JSON.stringify({ repo_url: repoUrl }),
      }),
  },

  projects: {
    list: () => request<Project[]>("/projects"),
    get: (id: string) => request<Project>(`/projects/${id}`),
    metrics: (id: string, range: "1h" | "6h" | "24h" = "1h") =>
      request<MetricsResponse>(`/projects/${id}/metrics?range=${range}`),
    create: (body: { name: string; namespace: string }) =>
      request<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),
    delete: (id: string) =>
      request<{ message: string }>(`/projects/${id}`, { method: "DELETE" }),
    setScaling: (id: string, body: { instance_size: InstanceSize; min_instances: number; max_instances: number }) =>
      request<Project>(`/projects/${id}/scaling`, { method: "PUT", body: JSON.stringify(body) }),
    vanityStatus: (id: string) =>
      request<{ state: "none" | "waiting_for_release" | "pending" | "live"; hostname: string | null }>(
        `/projects/${id}/subdomain/status`),
    setSubdomain: (id: string, subdomain: string | null) =>
      request<Project & { vanity_url: string | null }>(`/projects/${id}/subdomain`, {
        method: "PUT",
        body: JSON.stringify({ subdomain }),
      }),
  },

  deployments: {
    list: (projectId: string) =>
      request<Deployment[]>(`/projects/${projectId}/deployments`),
    get: (projectId: string, deploymentId: string) =>
      request<Deployment>(`/projects/${projectId}/deployments/${deploymentId}`),
    create: (
      projectId: string,
      body: { repo_url: string; port?: number; branch?: string; build_context?: string }
    ) =>
      request<Deployment>(`/projects/${projectId}/deployments`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    cancel: (projectId: string, deploymentId: string) =>
      request<{ status: string }>(`/projects/${projectId}/deployments/${deploymentId}/cancel`, {
        method: "POST",
      }),
    redeploy: (projectId: string, deploymentId: string) =>
      request<Deployment>(`/projects/${projectId}/deployments/${deploymentId}/redeploy`, {
        method: "POST",
      }),
    runtimeLogs: (projectId: string, deploymentId: string, opts: { since?: number; q?: string } = {}) => {
      const qs = new URLSearchParams();
      if (opts.since != null) qs.set("since", String(opts.since));
      if (opts.q) qs.set("q", opts.q);
      const tail = qs.toString() ? `?${qs}` : "";
      return request<{ lines: RuntimeLogLine[]; last: number | null }>(
        `/projects/${projectId}/deployments/${deploymentId}/runtime-logs${tail}`);
    },
    restart: (projectId: string, deploymentId: string) =>
      request<{ status: string }>(`/projects/${projectId}/deployments/${deploymentId}/restart`, {
        method: "POST",
      }),
  },

  builds: {
    list: (projectId: string, deploymentId: string) =>
      request<Build[]>(
        `/projects/${projectId}/deployments/${deploymentId}/builds`
      ),
    logs: async (projectId: string, deploymentId: string, buildId: string): Promise<string> => {
      // Logs endpoint streams plain text directly — no presigned URL needed.
      const token = await serverToken();
      const headers: Record<string, string> = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res = await fetch(
        `${BASE}/projects/${projectId}/deployments/${deploymentId}/builds/${buildId}/logs`,
        { headers }
      );
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      return res.text();
    },
  },

  audit: {
    list: (projectId: string) =>
      request<AuditLog[]>(`/projects/${projectId}/audit`),
    listGlobal: () =>
      request<AuditLog[]>("/audit"),
  },

  env: {
    list: (projectId: string) =>
      request<{ keys: string[] }>(`/projects/${projectId}/env`),
    put: (projectId: string, key: string, value: string) =>
      request<{ message: string }>(`/projects/${projectId}/env`, {
        method: "PUT",
        body: JSON.stringify({ key, value }),
      }),
    delete: (projectId: string, key: string) =>
      request<{ message: string }>(`/projects/${projectId}/env/${key}`, {
        method: "DELETE",
      }),
    apply: (projectId: string) =>
      request<{ message: string; deployment_id: string }>(`/projects/${projectId}/env/apply`, {
        method: "POST",
      }),
  },

  admin: {
    users: () => request<any[]>("/admin/users"),
    deployments: () => request<any[]>("/admin/deployments"),
    auditLogs: () => request<AuditLog[]>("/admin/audit-logs"),
    metrics: () => request<any>("/admin/metrics"),
    restartSystem: () =>
      request<{ status: string }>("/admin/system/restart", { method: "POST" }),
    setAnnouncement: (message: string, level: AnnouncementLevel) =>
      request<{ announcement: Announcement | null }>("/admin/platform/announcement", {
        method: "PUT",
        body: JSON.stringify({ message, level }),
      }),
    setDeployFreeze: (paused: boolean, reason = "") =>
      request<{ deploys_paused: boolean; pause_reason: string | null }>("/admin/platform/deploy-freeze", {
        method: "PUT",
        body: JSON.stringify({ paused, reason }),
      }),
    setSuspension: (userId: string, suspended: boolean, reason = "") =>
      request<{ user_id: string; suspended: boolean; reason: string | null }>(
        `/admin/users/${encodeURIComponent(userId)}/suspension`,
        { method: "PUT", body: JSON.stringify({ suspended, reason }) }),
    cost: () => request<SessionCost>("/admin/cost"),
  },

  platform: {
    status: () => request<PlatformStatus>("/platform/status"),
  },
};

export type AnnouncementLevel = "info" | "warning" | "critical";
export interface Announcement {
  message: string;
  level: AnnouncementLevel;
  updated_at?: string;
}
export interface PlatformStatus {
  announcement: Announcement | null;
  deploys_paused: boolean;
  pause_reason: string | null;
}
export interface SessionCost {
  session_started: string | null;
  uptime_hours: number;
  hourly_usd: number;
  session_usd: number;
  unpriced_nodes: string[];
  teardown: { idle_after_hours: number; hard_cap_hours: number; hours_to_hard_cap: number };
  nodes: {
    name: string;
    pool: string | null;
    machine_type: string | null;
    spot: boolean;
    hourly_usd: number | null;
    hours: number;
    cost_usd: number | null;
  }[];
}
