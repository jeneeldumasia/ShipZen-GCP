"use client";

import { useState } from "react";
import { Globe, RefreshCw, ExternalLink, X } from "lucide-react";
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

  async function save(value: string | null) {
    setSaving(true);
    try {
      const res = await api.projects.setSubdomain(projectId, value);
      setCurrent(res.subdomain ?? null);
      setDraft(res.subdomain ?? "");
      toast.success(value ? "Vanity URL saved. It goes live within a minute or two." : "Vanity URL removed");
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
            <a href={url} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1.5 font-mono text-sm text-brand hover:underline">
              {url.replace("https://", "")}
              <ExternalLink size={13} />
            </a>
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
