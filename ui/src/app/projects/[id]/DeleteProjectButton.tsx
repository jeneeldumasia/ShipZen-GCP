"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Trash2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export function DeleteProjectButton({ projectId, projectName }: { projectId: string; projectName: string }) {
  const router  = useRouter();
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);

  async function handleDelete() {
    setLoading(true);
    try {
      await api.projects.delete(projectId);
      toast.success("Project deleted");
      router.push("/");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to delete project");
    } finally {
      setLoading(false);
      setShowModal(false);
    }
  }

  return (
    <>
      <button onClick={() => setShowModal(true)} disabled={loading} className="btn-danger">
        {loading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
        Delete
      </button>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-canvas-bg border border-canvas-border rounded-2xl shadow-2xl max-w-md w-full p-6 animate-fade-in" style={{ animationDuration: '0.2s' }}>
            <div className="flex items-center gap-3 mb-4 text-danger">
              <div className="p-2 bg-danger/10 rounded-full">
                <Trash2 size={20} className="text-danger" />
              </div>
              <h2 className="text-xl font-bold text-text-primary tracking-tight">Delete Project</h2>
            </div>
            
            <p className="text-text-secondary mb-2">
              Are you sure you want to delete <strong className="text-text-primary">{projectName}</strong>?
            </p>
            <p className="text-sm text-text-secondary/80 mb-6 bg-danger/5 p-3 rounded-lg border border-danger/10">
              This will permanently terminate its Kubernetes namespace and all running workloads. This action cannot be undone.
            </p>
            
            <div className="flex justify-end gap-3">
              <button 
                onClick={() => setShowModal(false)} 
                disabled={loading}
                className="px-4 py-2 rounded-lg text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-canvas-border/50 transition-colors"
              >
                Cancel
              </button>
              <button 
                onClick={handleDelete} 
                disabled={loading}
                className="btn-danger"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : null}
                Yes, Delete Project
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
