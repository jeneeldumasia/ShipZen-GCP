"use client";

import { useState } from "react";
import { XCircle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export function CancelDeployButton({
  projectId,
  deploymentId,
}: {
  projectId: string;
  deploymentId: string;
}) {
  const [loading, setLoading] = useState(false);

  async function handleCancel() {
    setLoading(true);
    try {
      await api.deployments.cancel(projectId, deploymentId);
      toast.success("Deployment cancelled");
      // The page will automatically re-render when the WebSocket or auto-refresh picks up the Failed state
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to cancel");
      setLoading(false);
    }
  }

  return (
    <button
      onClick={handleCancel}
      disabled={loading}
      className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1.5 disabled:opacity-50 !text-red-500 hover:!bg-red-500/10 hover:!border-red-500/30"
    >
      <XCircle size={14} className={loading ? "opacity-50" : ""} />
      {loading ? "Cancelling..." : "Cancel"}
    </button>
  );
}
