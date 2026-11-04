"use client";

import { useState } from "react";
import { Megaphone, PauseCircle, PlayCircle } from "lucide-react";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import { api, type AnnouncementLevel, type PlatformStatus } from "@/lib/api";

const LEVELS: AnnouncementLevel[] = ["info", "warning", "critical"];

/** Banner every user sees, and the platform-wide deploy freeze. */
export function PlatformControls({ initial }: { initial: PlatformStatus }) {
  const router = useRouter();
  const [message, setMessage] = useState(initial.announcement?.message ?? "");
  const [level, setLevel] = useState<AnnouncementLevel>(initial.announcement?.level ?? "info");
  const [live, setLive] = useState(initial.announcement);
  const [paused, setPaused] = useState(initial.deploys_paused);
  const [reason, setReason] = useState(initial.pause_reason ?? "");
  const [busy, setBusy] = useState(false);

  async function saveBanner(text: string) {
    setBusy(true);
    try {
      const res = await api.admin.setAnnouncement(text, level);
      setLive(res.announcement);
      if (!res.announcement) setMessage("");
      toast.success(res.announcement ? "Announcement is live for everyone" : "Announcement removed");
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not update the announcement");
    } finally {
      setBusy(false);
    }
  }

  async function toggleFreeze() {
    setBusy(true);
    try {
      const res = await api.admin.setDeployFreeze(!paused, reason);
      setPaused(res.deploys_paused);
      toast.success(res.deploys_paused ? "New deploys are paused" : "Deploys resumed");
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not change the deploy freeze");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-6 animate-fade-in" style={{ animationDuration: "0.5s" }}>
      <h2 className="text-lg font-bold text-text-primary mb-6 flex items-center gap-2">
        <Megaphone size={18} className="text-brand" />
        Platform Controls
      </h2>

      <div className="space-y-3">
        <label className="text-sm font-medium text-text-secondary" htmlFor="announcement">
          Announcement banner
        </label>
        <textarea
          id="announcement"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          maxLength={300}
          rows={2}
          placeholder="e.g. Maintenance tonight 22:00–22:30 UTC; deploys may be slow."
          className="w-full rounded-lg border border-canvas-border bg-canvas-bg/50 px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-brand/50"
        />
        <div className="flex flex-wrap items-center gap-2">
          {LEVELS.map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => setLevel(l)}
              aria-pressed={level === l}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors capitalize ${
                level === l
                  ? "border-brand/50 bg-brand/10 text-text-primary"
                  : "border-canvas-border text-text-secondary hover:text-text-primary"
              }`}
            >
              {l}
            </button>
          ))}
          <div className="flex-1" />
          {live && (
            <button
              type="button"
              disabled={busy}
              onClick={() => saveBanner("")}
              className="px-3 py-1.5 rounded-lg text-xs font-medium border border-canvas-border text-text-secondary hover:text-text-primary disabled:opacity-50"
            >
              Remove
            </button>
          )}
          <button
            type="button"
            disabled={busy || !message.trim()}
            onClick={() => saveBanner(message)}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-brand text-white hover:opacity-90 disabled:opacity-50"
          >
            {live ? "Update" : "Publish"}
          </button>
        </div>
        <p className="text-xs text-text-secondary">
          {live
            ? `Live now (${live.level}). Every signed-in user sees it at the top of the page.`
            : "No announcement is showing."}
        </p>
      </div>

      <div className="mt-6 pt-6 border-t border-canvas-border space-y-3">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-text-primary">Deploy freeze</p>
            <p className="text-xs text-text-secondary mt-0.5">
              Stops new deploys everywhere: manual, push and PR previews. Running apps and builds already
              started are not touched.
            </p>
          </div>
          <span
            className={`shrink-0 px-2.5 py-1 rounded-full text-xs font-medium ${
              paused
                ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
            }`}
          >
            {paused ? "Paused" : "Deploys open"}
          </span>
        </div>
        <div className="flex gap-2">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={200}
            disabled={paused}
            placeholder="Reason shown to users (optional)"
            className="flex-1 rounded-lg border border-canvas-border bg-canvas-bg/50 px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:border-brand/50 disabled:opacity-60"
          />
          <button
            type="button"
            disabled={busy}
            onClick={toggleFreeze}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border disabled:opacity-50 ${
              paused
                ? "border-emerald-500/40 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10"
                : "border-amber-500/40 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10"
            }`}
          >
            {paused ? <PlayCircle size={14} /> : <PauseCircle size={14} />}
            {paused ? "Resume deploys" : "Pause deploys"}
          </button>
        </div>
      </div>
    </div>
  );
}
