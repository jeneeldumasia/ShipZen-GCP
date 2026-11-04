import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: { default: "ShipZen", template: "%s · ShipZen" },
  description: "Internal Developer Platform",
};

import { auth } from "@/auth";
import { getBaseUrl } from "@/lib/api";

import { ThemeProvider } from "@/components/ThemeProvider";
import { CommandPalette } from "@/components/CommandPalette";
import { Navigation } from "@/components/Navigation";
import { PlatformBanner } from "@/components/PlatformBanner";
import type { PlatformStatus } from "@/lib/api";
import { Toaster } from "sonner";

import { ViewTransitions } from 'next-view-transitions';

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  
  // Admin announcement and deploy freeze, shown above every page.
  let platformStatus: PlatformStatus | null = null;
  const token = (session as { accessToken?: string } | null)?.accessToken;
  if (token) {
    try {
      const res = await fetch(`${getBaseUrl()}/platform/status`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store'
      });
      if (res.ok) platformStatus = await res.json();
    } catch (e) {
      console.error("Failed to fetch platform status", e);
    }
  }

  if (!session) {
    return (
      <ViewTransitions>
        <html lang="en" suppressHydrationWarning>
          <body className="bg-canvas-bg min-h-screen antialiased">
            <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
              {children}
              <Toaster position="bottom-right" theme="system" />
            </ThemeProvider>
          </body>
        </html>
      </ViewTransitions>
    );
  }

  return (
    <ViewTransitions>
      <html lang="en" suppressHydrationWarning>
        <body className="bg-mesh min-h-screen antialiased">
          <ThemeProvider
            attribute="class"
            defaultTheme="system"
            enableSystem
            disableTransitionOnChange
          >
            <Navigation />
            {/* Pure Canvas Layout */}
            <div className="w-full min-h-screen flex flex-col items-center pt-24 px-8">
              <PlatformBanner status={platformStatus} />
              <main className="flex-1 w-full max-w-5xl animate-fade-in z-10 relative">
                {children}
              </main>
            </div>
            <CommandPalette />
            <Toaster position="bottom-right" theme="system" />
          </ThemeProvider>
        </body>
      </html>
    </ViewTransitions>
  );
}
