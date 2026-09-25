"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Loader2, CheckCircle2 } from "lucide-react";

export function ProjectProvisioningStatus({ projectId, initialStatus }: { projectId: string; initialStatus: string }) {
  const router = useRouter();
  const [status, setStatus] = useState(initialStatus);

  useEffect(() => {
    if (status === "Ready" || status === "Terminating" || status === "Failed") return;

    const interval = setInterval(async () => {
      try {
        const proj = await api.projects.get(projectId);
        if (proj.status !== status) {
          setStatus(proj.status);
          router.refresh();
        }
      } catch (e) {
        // ignore fetch errors
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [projectId, status, router]);

  if (status === "Ready" || status === "Terminating") {
    return null;
  }

  return (
    <div className="card p-6 mb-8 border-brand/30 bg-brand/5 relative overflow-hidden">
      {/* Animated background gradient */}
      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-brand/10 to-transparent animate-pulse" />
      
      <div className="flex items-center gap-4 relative z-10">
        <div className="w-10 h-10 rounded-full bg-brand/20 flex items-center justify-center flex-shrink-0 border border-brand/30">
          <Loader2 size={20} className="text-brand animate-spin" />
        </div>
        <div className="flex-1">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-bold text-text-primary">Provisioning Environment...</h3>
            <span className="text-xs font-mono text-brand font-medium">Setting up Kubernetes resources</span>
          </div>
          
          {/* Progress Bar Container */}
          <div className="w-full bg-black/10 dark:bg-white/10 h-2 rounded-full overflow-hidden shadow-inner border border-black/5 dark:border-white/5 relative">
            {/* Indeterminate Progress Bar */}
            <div className="absolute top-0 bottom-0 left-0 bg-brand w-1/3 rounded-full animate-[blob_2s_infinite]" />
          </div>
        </div>
      </div>
    </div>
  );
}
