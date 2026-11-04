import { AlertTriangle, Info, PauseCircle, Siren } from "lucide-react";
import type { PlatformStatus } from "@/lib/api";

const STYLES = {
  info: "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300",
  warning: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  critical: "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
} as const;
const ICONS = { info: Info, warning: AlertTriangle, critical: Siren } as const;

/** Admin announcement and deploy-freeze notice, shown to every signed-in user. */
export function PlatformBanner({ status }: { status: PlatformStatus | null }) {
  if (!status || (!status.announcement && !status.deploys_paused)) return null;
  const a = status.announcement;
  const Icon = a ? ICONS[a.level] : Info;
  return (
    <div className="w-full max-w-5xl space-y-2 mb-6 z-10 relative" role="status">
      {a && (
        <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${STYLES[a.level]}`}>
          <Icon size={16} className="mt-0.5 shrink-0" />
          <p className="whitespace-pre-line">{a.message}</p>
        </div>
      )}
      {status.deploys_paused && (
        <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${STYLES.warning}`}>
          <PauseCircle size={16} className="mt-0.5 shrink-0" />
          <p>
            New deploys are paused by a platform admin
            {status.pause_reason ? `: ${status.pause_reason}` : "."} Running apps are not affected.
          </p>
        </div>
      )}
    </div>
  );
}
