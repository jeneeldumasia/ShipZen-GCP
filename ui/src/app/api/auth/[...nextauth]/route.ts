import { handlers } from "@/auth"
import { NextRequest } from "next/server"

function withProxy(handler: any) {
  return (req: NextRequest) => {
    if (process.env.AUTH_URL?.startsWith("https://")) {
      const url = new URL(req.url)
      url.protocol = "https:"
      const headers = new Headers(req.headers)
      headers.set("x-forwarded-proto", "https")
      const newReq = new NextRequest(url.toString(), {
        headers,
        method: req.method,
        body: req.method === "POST" ? req.body : undefined,
        duplex: req.method === "POST" ? "half" : undefined,
      } as any)
      return handler(newReq)
    }
    return handler(req)
  }
}

/**
 * The browser reads its session from GET /api/auth/session. The session object
 * carries the user's GitHub token for server-side code (auth() in server
 * components and the /api/proxy route), so strip it from this one response:
 * browser JavaScript never sees the token (security finding H1).
 */
function withoutTokenForBrowser(handler: (req: NextRequest) => Promise<Response> | Response) {
  return async (req: NextRequest) => {
    const res = await handler(req)
    if (!new URL(req.url).pathname.endsWith("/session")) return res
    let body: unknown
    try {
      body = await res.clone().json()
    } catch {
      return res
    }
    if (!body || typeof body !== "object" || !("accessToken" in body)) return res
    const { accessToken: _drop, ...safe } = body as Record<string, unknown>
    const headers = new Headers(res.headers)
    headers.delete("content-length")
    return new Response(JSON.stringify(safe), { status: res.status, headers })
  }
}

export const GET = withoutTokenForBrowser(withProxy(handlers.GET))
export const POST = withProxy(handlers.POST)
