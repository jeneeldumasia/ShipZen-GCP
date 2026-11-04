"use client";

import { useEffect, useState } from "react";
import { Globe, RefreshCw, ExternalLink, X, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const SUFFIX = "-shipzen.jeneeldumasia.codes";

/**
 * Free vanity hostname for the project: <name>-shipzen.jeneeldumasia.codes,
 * always pointing at the live release (unlike per-release URLs, which change
 * with every deploy).
 */
export function VanityDomain({ projectId, initial }: { projectId: string; initial: string | null }) {
  const [current, setCurrent] = useState<string | null>(initial);
  const [draft, setDraft] = useState(initial ?? "");
  const [saving, setSaving] = useState(false);
  // Is the URL actually reachable yet? Saving takes effect within a minute or so
  // (controller, GitOps, gateway); until then the hostname would answer 404.
  const [status, setStatus] = useState<"none" | "waiting_for_release" | "pending" | "live" | null>(null);

  useEffect(() => {
    if (!current) { setStatus("none"); return; }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      try {
        const s = await api.projects.vanityStatus(projectId);
        if (cancelled) return;
        setStatus(s.state);
        if (s.state !== "live") timer = setTimeout(check, 5000);
      } catch {
        if (!cancelled) timer = setTimeout(check, 10000);
      }
    };
    setStatus("pending");
    check();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [projectId, current]);

  async function save(value: string | null) {
    setSaving(true);
    try {
      const res = await api.projects.setSubdomain(projectId, value);
      setCurrent(res.subdomain ?? null);
      setDraft(res.subdomain ?? "");
      toast.success(value ? "Vanity URL saved. Setting it up…" : "Vanity URL removed");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the vanity URL");
    } finally {
      setSaving(false);
    }
  }

  const url = current ? `https://${current}${SUFFIX}` : null;

  return (
    <div className="card overflow-hidden mt-6">
      <div className="px-6 py-4 border-b border-canvas-border flex items-center gap-2">
        <Globe size={16} className="text-text-secondary" />
        <h2 className="text-sm font-semibold text-text-primary">Vanity URL</h2>
        <span className="text-xs text-text-secondary">Free · always points at the live release</span>
      </div>

      <div className="p-6">
        {url && (
          <div className="flex items-center gap-3 mb-5">
            {status === "live" ? (
              <a href={url} target="_blank" rel="noopener noreferrer"
                 className="inline-flex items-center gap-1.5 font-mono text-sm text-brand hover:underline">
                {url.replace("https://", "")}
                <ExternalLink size={13} />
              </a>
            ) : (
              <span className="inline-flex items-center gap-1.5 font-mono text-sm text-text-secondary">
                {url.replace("https://", "")}
              </span>
            )}
            {status === "live" && (
              <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">Live</span>
            )}
            {(status === "pending" || status === null) && (
              <span className="inline-flex items-center gap-1 text-xs text-text-secondary">
                <Loader2 size={12} className="animate-spin" /> Setting up… usually under a minute
              </span>
            )}
            {status === "waiting_for_release" && (
              <span className="text-xs text-text-secondary">Goes live with your next successful deploy</span>
            )}
            <button onClick={() => save(null)} disabled={saving}
                    className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-red-500 disabled:opacity-50">
              <X size={13} /> Remove
            </button>
          </div>
        )}

        <form
          onSubmit={(e) => { e.preventDefault(); if (draft.trim()) save(draft.trim().toLowerCase()); }}
          className="flex items-end gap-4"
        >
          <div className="flex-1">
            <label className="block text-xs font-medium text-text-secondary mb-1">
              {current ? "Change name" : "Choose a name"}
            </label>
            <div className="flex items-center bg-black/5 dark:bg-white/5 border border-canvas-border rounded focus-within:border-brand">
              <span className="pl-3 text-sm text-text-secondary font-mono">https://</span>
              <input
                type="text"
                value={draft}
                onChange={(e) => setDraft(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
                placeholder="myapp"
                maxLength={40}
                aria-label="Vanity name"
                className="flex-1 min-w-0 bg-transparent px-1 py-2 text-sm font-mono focus:outline-none"
              />
              <span className="pr-3 text-sm text-text-secondary font-mono">{SUFFIX}</span>
            </div>
            <p className="text-xs text-text-secondary mt-1.5">
              3–40 lowercase letters, digits and hyphens. Your app is reachable there once a release is live.
            </p>
          </div>
          <button type="submit" disabled={saving || !draft.trim() || draft === current}
                  className="btn-primary disabled:opacity-50 py-2">
            {saving ? <RefreshCw size={16} className="animate-spin" /> : <Globe size={16} />}
            Save
          </button>
        </form>
      </div>
    </div>
  );
}
