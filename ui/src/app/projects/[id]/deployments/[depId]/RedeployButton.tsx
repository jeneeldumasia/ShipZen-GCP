"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export function RedeployButton({ projectId, repoUrl, port }: { projectId: string; repoUrl: string; port: number }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handleRedeploy() {
    setLoading(true);
    try {
      const newDeployment = await api.deployments.create(projectId, { repo_url: repoUrl, port });
      toast.success("Deployment queued successfully");
      router.push(`/projects/${projectId}/deployments/${newDeployment.deployment_id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to redeploy");
      setLoading(false);
    }
  }

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      // Shortcut R: Redeploy
      if (e.key.toLowerCase() === "r" && !e.metaKey && !e.ctrlKey && e.target === document.body && !loading) {
        e.preventDefault();
        handleRedeploy();
      }
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [loading, projectId, repoUrl, port]);

  return (
    <button
      onClick={handleRedeploy}
      disabled={loading}
      className="btn-primary text-xs py-1.5 px-3 flex items-center gap-1.5 disabled:opacity-50"
    >
      <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
      {loading ? "Redeploying..." : "Redeploy"}
    </button>
  );
}
