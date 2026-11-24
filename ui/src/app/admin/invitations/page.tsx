"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { MailPlus, ShieldAlert, User as UserIcon, Trash2 } from "lucide-react";
import { api, type Invitation } from "@/lib/api";

function status(inv: Invitation): { label: string; tone: string } {
  if (inv.accepted_at) return { label: `Accepted ${new Date(inv.accepted_at).toLocaleDateString()}`, tone: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" };
  if (inv.expires_at && new Date(inv.expires_at) < new Date()) return { label: "Expired", tone: "bg-canvas-border text-text-secondary" };
  return { label: inv.expires_at ? `Pending until ${new Date(inv.expires_at).toLocaleDateString()}` : "Pending", tone: "bg-amber-500/15 text-amber-600 dark:text-amber-400" };
}

export default function AdminInvitationsPage() {
  const [invitations, setInvitations] = useState<Invitation[] | null>(null);
  const [who, setWho] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [days, setDays] = useState<string>("14");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setInvitations(await api.admin.invitations());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not load invitations");
      setInvitations([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    const value = who.trim();
    if (!value) return;
    setBusy(true);
    try {
      await api.admin.createInvitation({
        ...(value.includes("@") && !value.startsWith("@") ? { email: value } : { github_login: value.replace(/^@/, "") }),
        role,
        expires_in_days: days === "never" ? null : Number(days),
      });
      toast.success(`Invited ${value}`);
      setWho("");
      setRole("user");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create the invitation");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(inv: Invitation) {
    const name = inv.github_login || inv.email;
    if (inv.accepted_at && !window.confirm(`${name} accepted this invitation. Revoking it removes their access. Continue?`)) return;
    try {
      await api.admin.revokeInvitation(inv.id);
      toast.success(`Revoked ${name}`);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not revoke the invitation");
    }
  }

  const input = "rounded-lg border border-canvas-border bg-canvas-bg/50 px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-brand";

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-8">
        <div className="p-3 bg-brand/20 rounded-xl shadow-glow">
          <MailPlus className="w-6 h-6 text-brand" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-text-primary tracking-tight">Invitations</h1>
          <p className="text-text-secondary mt-1">
            Let someone in by GitHub login or verified email. It works straight away, with no redeploy.
          </p>
        </div>
      </div>

      <form onSubmit={invite} className="flex flex-wrap items-end gap-3 rounded-xl border border-canvas-border bg-canvas-card p-4">
        <label className="flex flex-col gap-1 text-xs text-text-secondary grow min-w-[14rem]">
          GitHub login or email
          <input value={who} onChange={(e) => setWho(e.target.value)} placeholder="octocat or someone@example.com"
            maxLength={255} className={input} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as "user" | "admin")} className={input}>
            <option value="user">User</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Accept within
          <select value={days} onChange={(e) => setDays(e.target.value)} className={input}>
            <option value="1">1 day</option>
            <option value="7">7 days</option>
            <option value="14">14 days</option>
            <option value="30">30 days</option>
            <option value="never">No limit</option>
          </select>
        </label>
        <button type="submit" disabled={busy || !who.trim()}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand/90 disabled:opacity-50">
          {busy ? "Inviting…" : "Invite"}
        </button>
      </form>

      <div className="rounded-xl border border-canvas-border bg-canvas-bg/40 overflow-hidden backdrop-blur-xl shadow-2xl">
        <table className="w-full text-left text-sm text-text-secondary">
          <thead className="bg-canvas-border/50 text-xs uppercase font-semibold text-text-primary">
            <tr>
              <th className="px-6 py-4">Invited</th>
              <th className="px-6 py-4">Role</th>
              <th className="px-6 py-4">Status</th>
              <th className="px-6 py-4">Created</th>
              <th className="px-6 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-canvas-border">
            {invitations === null && (
              <tr><td colSpan={5} className="px-6 py-8 text-center">Loading…</td></tr>
            )}
            {invitations?.length === 0 && (
              <tr><td colSpan={5} className="px-6 py-8 text-center">No invitations yet.</td></tr>
            )}
            {invitations?.map((inv) => {
              const s = status(inv);
              return (
                <tr key={inv.id} className="hover:bg-canvas-border/50 transition-colors">
                  <td className="px-6 py-4 text-text-primary">
                    {inv.github_login ? <span className="font-mono">@{inv.github_login}</span> : inv.email}
                  </td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                      inv.role === "admin" ? "bg-red-500/20 text-red-600 dark:text-red-400" : "bg-canvas-border text-text-secondary"}`}>
                      {inv.role === "admin" ? <ShieldAlert size={12} /> : <UserIcon size={12} />}
                      {inv.role}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex px-2.5 py-1 rounded-full text-xs font-medium ${s.tone}`}>{s.label}</span>
                  </td>
                  <td className="px-6 py-4">{new Date(inv.created_at).toLocaleDateString()}</td>
                  <td className="px-6 py-4 text-right">
                    <button type="button" onClick={() => revoke(inv)}
                      className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-red-500/30 text-red-600 dark:text-red-400 hover:bg-red-500/10">
                      <Trash2 size={12} /> Revoke
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
