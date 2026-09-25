"use client";

import { useState, useEffect } from "react";
import { Lock, Plus, Trash2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export function EnvVars({ projectId }: { projectId: string }) {
  const [keys, setKeys] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");
  const [saving, setSaving] = useState(false);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);

  useEffect(() => {
    loadKeys();
  }, [projectId]);

  async function loadKeys() {
    try {
      const res = await api.env.list(projectId);
      setKeys(res.keys || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!newKey || !newVal) return;
    setSaving(true);
    try {
      await api.env.put(projectId, newKey, newVal);
      setNewKey("");
      setNewVal("");
      await loadKeys();
      toast.success("Environment variable saved");
    } catch {
      toast.error("Failed to save environment variable");
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete(key: string) {
    try {
      await api.env.delete(projectId, key);
      await loadKeys();
      toast.success("Environment variable deleted");
    } catch {
      toast.error("Failed to delete environment variable");
    } finally {
      setDeletingKey(null);
    }
  }

  return (
    <div className="card overflow-hidden mt-6">
      <div className="px-6 py-4 border-b border-canvas-border flex items-center gap-2">
        <Lock size={16} className="text-text-secondary" />
        <h2 className="text-sm font-semibold text-text-primary">Environment Variables</h2>
      </div>

      <div className="p-6">
        <form onSubmit={handleAdd} className="flex items-end gap-4 mb-6">
          <div className="flex-1">
            <label className="block text-xs font-medium text-text-secondary mb-1">Key</label>
            <input
              type="text"
              value={newKey}
              onChange={e => setNewKey(e.target.value.toUpperCase())}
              placeholder="API_KEY"
              className="w-full bg-black/5 dark:bg-white/5 border border-canvas-border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:border-brand"
            />
          </div>
          <div className="flex-1">
            <label className="block text-xs font-medium text-text-secondary mb-1">Value</label>
            <input
              type="password"
              value={newVal}
              onChange={e => setNewVal(e.target.value)}
              placeholder="••••••••••••••••"
              className="w-full bg-black/5 dark:bg-white/5 border border-canvas-border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:border-brand"
            />
          </div>
          <button
            type="submit"
            disabled={saving || !newKey || !newVal}
            className="btn-primary disabled:opacity-50 py-2"
          >
            {saving ? <RefreshCw size={16} className="animate-spin" /> : <Plus size={16} />}
            Add
          </button>
        </form>

        {loading ? (
          <div className="text-sm text-text-secondary animate-pulse">Loading variables...</div>
        ) : keys.length === 0 ? (
          <div className="text-sm text-text-secondary">No environment variables set.</div>
        ) : (
          <div className="border border-canvas-border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-black/5 dark:bg-white/5">
                <tr>
                  <th className="text-left px-4 py-2 font-semibold text-text-secondary text-xs uppercase tracking-wide">Key</th>
                  <th className="text-left px-4 py-2 font-semibold text-text-secondary text-xs uppercase tracking-wide">Value</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-canvas-border">
                {keys.map(k => (
                  <tr key={k} className="group">
                    <td className="px-4 py-3 font-mono text-xs">{k}</td>
                    <td className="px-4 py-3 font-mono text-xs text-text-secondary">••••••••</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => setDeletingKey(k)}
                        className="text-red-500 hover:text-red-600 opacity-0 group-hover:opacity-100 transition-opacity"
                        title="Delete"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {deletingKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-canvas-bg border border-canvas-border rounded-2xl shadow-2xl max-w-sm w-full p-6 animate-fade-in" style={{ animationDuration: '0.2s' }}>
            <div className="flex items-center gap-3 mb-4 text-danger">
              <div className="p-2 bg-danger/10 rounded-full">
                <Trash2 size={20} className="text-danger" />
              </div>
              <h2 className="text-xl font-bold text-text-primary tracking-tight">Delete Variable</h2>
            </div>
            
            <p className="text-text-secondary mb-6">
              Are you sure you want to delete <strong className="text-text-primary font-mono bg-canvas-border/30 px-1 rounded">{deletingKey}</strong>? This action cannot be undone.
            </p>
            
            <div className="flex justify-end gap-3">
              <button 
                onClick={() => setDeletingKey(null)} 
                className="px-4 py-2 rounded-lg text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-canvas-border/50 transition-colors"
              >
                Cancel
              </button>
              <button 
                onClick={() => confirmDelete(deletingKey)} 
                className="btn-danger"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
