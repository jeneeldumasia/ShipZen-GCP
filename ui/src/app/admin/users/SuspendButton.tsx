"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api } from "@/lib/api";

/** Suspend (with an optional reason) or restore a user. */
export function SuspendButton({ userId, suspended, isAdmin }: { userId: string; suspended: boolean; isAdmin: boolean }) {
  const router = useRouter();
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function apply(next: boolean) {
    setBusy(true);
    try {
      await api.admin.setSuspension(userId, next, reason);
      toast.success(next ? "User suspended" : "User restored");
      setAsking(false);
      setReason("");
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not change the suspension");
    } finally {
      setBusy(false);
    }
  }

  const btn = "text-xs px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50";

  if (suspended) {
    return (
      <button type="button" disabled={busy} onClick={() => apply(false)}
        className={`${btn} border border-emerald-500/40 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10`}>
        Restore
      </button>
    );
  }
  if (isAdmin) {
    return <span className="text-xs text-text-secondary" title="Demote first to suspend">—</span>;
  }
  if (!asking) {
    return (
      <button type="button" onClick={() => setAsking(true)}
        className={`${btn} border border-red-500/30 text-red-600 dark:text-red-400 hover:bg-red-500/10`}>
        Suspend
      </button>
    );
  }
  return (
    <div className="flex items-center justify-end gap-2">
      <input
        autoFocus
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        maxLength={300}
        placeholder="Reason (optional)"
        className="w-40 rounded-lg border border-canvas-border bg-canvas-bg/50 px-2 py-1 text-xs text-text-primary focus:outline-none"
      />
      <button type="button" disabled={busy} onClick={() => apply(true)}
        className={`${btn} bg-red-500/90 text-white hover:bg-red-500`}>
        Confirm
      </button>
      <button type="button" disabled={busy} onClick={() => setAsking(false)}
        className={`${btn} text-text-secondary hover:text-text-primary`}>
        Cancel
      </button>
    </div>
  );
}
