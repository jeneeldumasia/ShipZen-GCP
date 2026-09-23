"use client";

import { useEffect, useRef, useState } from "react";
import { Terminal, Wifi, WifiOff } from "lucide-react";
import { getWsBaseUrl } from "@/lib/api";

const ANSI_RE = /[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g;

interface Props {
  projectId: string;
  deploymentId: string;
  token?: string;
}

/**
 * Inline live-log terminal shown on the deployment page while a build is active.
 * Connects directly to the WS log endpoint and streams output in real-time.
 * Automatically stops when the server closes the connection (build finished).
 */
export function LiveLogPanel({ projectId, deploymentId, token }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [ended, setEnded] = useState(false);
  const scrollRef = useRef<HTMLPreElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!token) return;

    const wsUrl = getWsBaseUrl();

    const ws = new WebSocket(
      `${wsUrl}/ws/projects/${projectId}/deployments/${deploymentId}/logs`
    );
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({ token }));
    };

    ws.onmessage = (e: MessageEvent) => {
      const line = (e.data as string).replace(ANSI_RE, "");
      if (line.trim() === "ping" || line.trim() === '{"type": "ping"}') return;
      setLines((prev) => [...prev, line].slice(-500));
    };

    ws.onerror = () => {
      setLines((prev) => [...prev, "\n[connection error]"]);
      setConnected(false);
      setEnded(true);
    };

    ws.onclose = () => {
      setConnected(false);
      setEnded(true);
    };

    return () => {
      ws.close();
    };
  }, [projectId, deploymentId, token]);

  // Auto-scroll to bottom on new lines
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div className="w-full flex flex-col items-center justify-center relative">
      {lines.length === 0 && !ended ? (
        <div className="h-64 w-full flex items-center justify-center text-text-secondary font-mono text-xs uppercase tracking-widest">
          <Wifi size={14} className="text-brand mr-2" />
          Awaiting Telemetry...
        </div>
      ) : (
        <div 
          ref={scrollRef}
          className="h-64 w-full max-w-3xl bg-surface/30 border border-border/50 rounded-xl overflow-y-auto p-4 flex flex-col font-mono text-[11px] text-text-secondary custom-scrollbar"
        >
          {lines.map((line, idx) => (
            <div key={idx} className="whitespace-pre-wrap break-all py-0.5">
              {line}
            </div>
          ))}
          
          {connected && (
            <div className="mt-4 text-[10px] text-brand uppercase tracking-widest flex items-center gap-2 opacity-80">
              <span className="w-1.5 h-1.5 rounded-full bg-brand animate-pulse" /> Streaming
            </div>
          )}
        </div>
      )}
    </div>
  );
}
