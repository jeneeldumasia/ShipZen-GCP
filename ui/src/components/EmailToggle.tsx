"use client";

import { useState } from "react";
import { Bell, BellOff } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

/** Deploy emails (live / failed / down) to your GitHub address: on or off. */
export function EmailToggle({ initial }: { initial: boolean }) {
  const [on, setOn] = useState(initial);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    setBusy(true);
    try {
      const res = await api.users.setNotifications(!on);
      setOn(res.email_notifications);
      toast.success(res.email_notifications ? "Deploy emails on" : "Deploy emails off");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not change email settings");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      aria-pressed={on}
      className="p-1.5 rounded-full text-text-secondary hover:text-text-primary hover:bg-canvas-border/30 transition-all disabled:opacity-50"
      title={on ? "Deploy emails are on (click to turn off)" : "Deploy emails are off (click to turn on)"}
    >
      {on ? <Bell size={14} /> : <BellOff size={14} />}
    </button>
  );
}
