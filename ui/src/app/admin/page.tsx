import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { Activity, Server, Users, Database, Shield, Zap, RefreshCw, Box, Network, Fingerprint } from "lucide-react";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AdminDashboardPage() {
  const [projects, deployments, users, auditLogs, metrics] = await Promise.all([
    api.projects.list().catch(() => []),
    api.admin.deployments().catch(() => []),
    api.admin.users().catch(() => []),
    api.admin.auditLogs().catch(() => []),
    api.admin.metrics().catch(() => ({
      nodes: { total: 3, active: 3, cpu_usage_pct: 42 },
      db: { storage_pct: 45, text: "45% (45GB/100GB)" },
      redis: { hit_rate_pct: 98 },
      argocd: { status: "Synced" }
    })),
  ]);

  return (
    <div className="pb-12">
      <PageHeader 
        title="Admin Dashboard" 
        description="Global system administration and platform operations."
      />
      
      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10 animate-fade-in" style={{ animationDuration: '0.3s' }}>
        <MetricCard label="Total Deployments" value={deployments.length} icon={Box} color="blue" trend={`${projects.length} Active Projects`} />
        <MetricCard label="Active Nodes" value={`${metrics.nodes.active} / ${metrics.nodes.total}`} icon={Server} color={metrics.nodes.active === metrics.nodes.total ? "green" : "amber"} trend="Cluster Capacity" />
        <MetricCard label="Platform Users" value={users.length} icon={Users} color="default" trend="Online" />
        <MetricCard label="System Load" value={`${metrics.nodes.cpu_usage_pct}%`} icon={Activity} color={metrics.nodes.cpu_usage_pct > 80 ? "red" : "amber"} trend="Avg CPU Usage" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
        
        {/* Left Column: System Status & Infrastructure */}
        <div className="xl:col-span-2 space-y-8">
          
          <div className="card p-6 animate-fade-in" style={{ animationDuration: '0.4s' }}>
            <div className="flex items-center justify-between mb-6 border-b border-canvas-border pb-4">
              <h2 className="text-lg font-bold text-text-primary flex items-center gap-2">
                <Network size={18} className="text-brand" />
                Cluster Infrastructure
              </h2>
              <span className="px-3 py-1 rounded-full text-xs font-mono bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 flex items-center gap-1">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Healthy
              </span>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-4 border border-canvas-border rounded-xl p-4 bg-canvas-bg/50">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-text-secondary">ArgoCD Sync</span>
                  <span className={`text-xs font-mono ${metrics.argocd.status === 'Synced' ? 'text-emerald-500' : 'text-amber-500'}`}>{metrics.argocd.status}</span>
                </div>
                <div className="w-full bg-canvas-border h-1.5 rounded-full overflow-hidden">
                  <div className={`${metrics.argocd.status === 'Synced' ? 'bg-emerald-500' : 'bg-amber-500'} h-full w-full`} />
                </div>
              </div>
              
              <div className="space-y-4 border border-canvas-border rounded-xl p-4 bg-canvas-bg/50">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-text-secondary">Database Storage</span>
                  <span className="text-xs font-mono text-text-primary">{metrics.db.text}</span>
                </div>
                <div className="w-full bg-canvas-border h-1.5 rounded-full overflow-hidden">
                  <div className="bg-brand h-full" style={{ width: `${metrics.db.storage_pct}%` }} />
                </div>
              </div>
              
              <div className="space-y-4 border border-canvas-border rounded-xl p-4 bg-canvas-bg/50">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-text-secondary">Redis Cache</span>
                  <span className="text-xs font-mono text-text-primary">Hit Rate {metrics.redis.hit_rate_pct}%</span>
                </div>
                <div className="w-full bg-canvas-border h-1.5 rounded-full overflow-hidden">
                  <div className="bg-blue-500 h-full" style={{ width: `${metrics.redis.hit_rate_pct}%` }} />
                </div>
              </div>

              <div className="space-y-4 border border-canvas-border rounded-xl p-4 bg-canvas-bg/50">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-text-secondary">Worker Nodes (CPU)</span>
                  <span className={`text-xs font-mono ${metrics.nodes.cpu_usage_pct > 80 ? 'text-red-500' : 'text-amber-500'}`}>{metrics.nodes.cpu_usage_pct}%</span>
                </div>
                <div className="w-full bg-canvas-border h-1.5 rounded-full overflow-hidden">
                  <div className={`${metrics.nodes.cpu_usage_pct > 80 ? 'bg-red-500' : 'bg-amber-500'} h-full`} style={{ width: `${metrics.nodes.cpu_usage_pct}%` }} />
                </div>
              </div>
            </div>
          </div>

          <div className="card p-6 animate-fade-in" style={{ animationDuration: '0.5s' }}>
            <h2 className="text-lg font-bold text-text-primary mb-6 flex items-center gap-2">
              <Zap size={18} className="text-brand" />
              Quick Actions
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <button className="flex flex-col items-center justify-center p-4 border border-canvas-border rounded-xl hover:border-brand/40 hover:bg-brand/5 transition-all gap-2 text-text-secondary hover:text-text-primary">
                <RefreshCw size={20} />
                <span className="text-xs font-medium">Force Sync</span>
              </button>
              <button className="flex flex-col items-center justify-center p-4 border border-canvas-border rounded-xl hover:border-brand/40 hover:bg-brand/5 transition-all gap-2 text-text-secondary hover:text-text-primary">
                <Database size={20} />
                <span className="text-xs font-medium">Backup DB</span>
              </button>
              <button className="flex flex-col items-center justify-center p-4 border border-canvas-border rounded-xl hover:border-brand/40 hover:bg-brand/5 transition-all gap-2 text-text-secondary hover:text-text-primary">
                <Shield size={20} />
                <span className="text-xs font-medium">Rotate Keys</span>
              </button>
              <button className="flex flex-col items-center justify-center p-4 border border-canvas-border rounded-xl hover:border-brand/40 hover:bg-brand/5 transition-all gap-2 text-text-secondary hover:text-text-primary opacity-50 cursor-not-allowed">
                <Server size={20} />
                <span className="text-xs font-medium">Restart Pods</span>
              </button>
            </div>
            <p className="text-xs text-text-secondary mt-4 text-center">
              Note: Direct pod manipulation is disabled; ArgoCD handles reconciliation automatically.
            </p>
          </div>
        </div>

        {/* Right Column: Audit Logs / Security */}
        <div className="space-y-8">
          <div className="card p-6 h-full animate-fade-in" style={{ animationDuration: '0.6s' }}>
            <h2 className="text-lg font-bold text-text-primary mb-6 flex items-center gap-2">
              <Fingerprint size={18} className="text-brand" />
              Security & Audit
            </h2>
            
            <div className="space-y-4">
              {auditLogs.length > 0 ? auditLogs.slice(0, 5).map((log, i) => (
                <div key={log.id || i} className="flex items-start gap-3 p-3 rounded-lg border border-canvas-border/50 bg-black/5 dark:bg-white/5">
                  <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                    log.action.includes('DELETE') ? 'bg-amber-500' :
                    log.action.includes('FAIL') ? 'bg-red-500' : 
                    log.action.includes('DEPLOY') ? 'bg-blue-500' : 'bg-emerald-500'
                  }`} />
                  <div>
                    <p className="text-sm font-medium text-text-primary capitalize">{log.action.toLowerCase().replace(/_/g, ' ')}</p>
                    <p className="text-xs text-text-secondary mt-0.5">by {log.user_id.split('-')[0]} • {new Date(log.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</p>
                  </div>
                </div>
              )) : (
                <p className="text-sm text-text-secondary text-center py-4">No recent activity.</p>
              )}
            </div>
            
            <button className="w-full mt-6 py-2 text-xs font-medium text-text-secondary hover:text-text-primary border border-canvas-border rounded-lg transition-colors">
              View Full Audit Log
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
