import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { Activity, Server, Users, Database, Shield, Zap, RefreshCw, Box, Network, Fingerprint } from "lucide-react";

export default function AdminDashboardPage() {
  return (
    <div className="pb-12">
      <PageHeader 
        title="Admin Dashboard" 
        description="Global system administration and platform operations."
      />
      
      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10 animate-fade-in" style={{ animationDuration: '0.3s' }}>
        <MetricCard label="Total Deployments" value="1,284" icon={Box} color="blue" trend="+12% from last week" />
        <MetricCard label="Active Nodes" value="12 / 12" icon={Server} color="green" trend="100% capacity" />
        <MetricCard label="Platform Users" value="84" icon={Users} color="default" trend="2 pending invites" />
        <MetricCard label="System Load" value="42%" icon={Activity} color="amber" trend="Stable" />
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
                  <span className="text-xs font-mono text-emerald-500">Synced</span>
                </div>
                <div className="w-full bg-canvas-border h-1.5 rounded-full overflow-hidden">
                  <div className="bg-emerald-500 h-full w-full" />
                </div>
              </div>
              
              <div className="space-y-4 border border-canvas-border rounded-xl p-4 bg-canvas-bg/50">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-text-secondary">Database Storage</span>
                  <span className="text-xs font-mono text-text-primary">45% (45GB/100GB)</span>
                </div>
                <div className="w-full bg-canvas-border h-1.5 rounded-full overflow-hidden">
                  <div className="bg-brand h-full w-[45%]" />
                </div>
              </div>
              
              <div className="space-y-4 border border-canvas-border rounded-xl p-4 bg-canvas-bg/50">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-text-secondary">Redis Cache</span>
                  <span className="text-xs font-mono text-text-primary">Hit Rate 98%</span>
                </div>
                <div className="w-full bg-canvas-border h-1.5 rounded-full overflow-hidden">
                  <div className="bg-blue-500 h-full w-[98%]" />
                </div>
              </div>

              <div className="space-y-4 border border-canvas-border rounded-xl p-4 bg-canvas-bg/50">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-text-secondary">Worker Nodes (CPU)</span>
                  <span className="text-xs font-mono text-amber-500">72%</span>
                </div>
                <div className="w-full bg-canvas-border h-1.5 rounded-full overflow-hidden">
                  <div className="bg-amber-500 h-full w-[72%]" />
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
              {[
                { action: "Admin Login", user: "jeneel.dumasia", time: "2 mins ago", type: "info" },
                { action: "Project Deleted", user: "system", time: "14 mins ago", type: "warning" },
                { action: "ArgoCD Sync", user: "webhook", time: "1 hour ago", type: "success" },
                { action: "Database Backup", user: "cron", time: "3 hours ago", type: "info" },
                { action: "Failed Auth", user: "unknown", time: "5 hours ago", type: "danger" },
              ].map((log, i) => (
                <div key={i} className="flex items-start gap-3 p-3 rounded-lg border border-canvas-border/50 bg-black/5 dark:bg-white/5">
                  <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                    log.type === 'info' ? 'bg-blue-500' :
                    log.type === 'warning' ? 'bg-amber-500' :
                    log.type === 'danger' ? 'bg-red-500' : 'bg-emerald-500'
                  }`} />
                  <div>
                    <p className="text-sm font-medium text-text-primary">{log.action}</p>
                    <p className="text-xs text-text-secondary mt-0.5">by {log.user} • {log.time}</p>
                  </div>
                </div>
              ))}
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
