/**
 * Backend-for-frontend proxy (security finding H1).
 *
 * Browser code calls /api/proxy/<api path> on the UI's own origin. This route
 * runs on the server, reads the signed-in user's GitHub token from the
 * (httpOnly, encrypted) session cookie and forwards the call to the API with
 * it. The token itself never reaches browser JavaScript, so an XSS bug can no
 * longer steal a GitHub credential.
 */
import { auth } from "@/auth"
import { NextRequest } from "next/server"

const API_BASE = process.env.KUBERNETES_SERVICE_HOST
  ? "http://shipzen-api.shipzen-system.svc.cluster.local:80"
  : (process.env.API_URL ?? "http://localhost:8000")

// Hop-by-hop and cookie headers never go to the API.
const DROP_REQUEST_HEADERS = new Set([
  "host", "connection", "cookie", "authorization", "content-length",
  "transfer-encoding", "keep-alive", "upgrade",
])

function sameOrigin(req: NextRequest): boolean {
  // Cookie-authenticated writes must come from our own pages (CSRF). Browsers
  // always send Origin on cross-site POST/PUT/DELETE.
  const origin = req.headers.get("origin")
  if (!origin) return true
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host")
  try {
    return new URL(origin).host === host
  } catch {
    return false
  }
}

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  if (req.method !== "GET" && req.method !== "HEAD" && !sameOrigin(req)) {
    return Response.json({ detail: "Cross-site request refused" }, { status: 403 })
  }
  const session = await auth()
  const token = (session as { accessToken?: string; error?: string } | null)?.accessToken
  if (!session || !token || (session as { error?: string }).error) {
    return Response.json({ detail: "Not signed in" }, { status: 401 })
  }

  const { path } = await ctx.params
  const target = new URL(`${API_BASE}/${path.map(encodeURIComponent).join("/")}`)
  target.search = new URL(req.url).search

  const headers = new Headers()
  req.headers.forEach((value, key) => {
    if (!DROP_REQUEST_HEADERS.has(key.toLowerCase())) headers.set(key, value)
  })
  headers.set("Authorization", `Bearer ${token}`)

  const hasBody = !["GET", "HEAD"].includes(req.method)
  const upstream = await fetch(target, {
    method: req.method,
    headers,
    body: hasBody ? await req.arrayBuffer() : undefined,
    redirect: "manual",
    cache: "no-store",
  })

  const out = new Headers()
  upstream.headers.forEach((value, key) => {
    if (!["content-encoding", "content-length", "transfer-encoding", "connection"].includes(key.toLowerCase())) {
      out.set(key, value)
    }
  })
  return new Response(upstream.body, { status: upstream.status, headers: out })
}

export const GET = forward
export const POST = forward
export const PUT = forward
export const PATCH = forward
export const DELETE = forward
