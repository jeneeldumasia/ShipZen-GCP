"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";

export function CopyErrorButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="ml-auto flex items-center gap-1 text-xs px-2 py-1 border border-red-500/30 rounded bg-red-500/10 hover:bg-red-500/20 transition-colors uppercase tracking-widest font-bold"
      title="Copy Error Log"
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
