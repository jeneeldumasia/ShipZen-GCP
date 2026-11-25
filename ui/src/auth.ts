import NextAuth from "next-auth"
import GitHubProvider from "next-auth/providers/github"
import CredentialsProvider from "next-auth/providers/credentials"

// Use GitHub if configured, otherwise use Stub Credentials
const providers = []

const githubClientId = process.env.OAUTH_CLIENT_ID || process.env.SHIPZEN_OAUTH_CLIENT_ID;
const githubClientSecret = process.env.OAUTH_CLIENT_SECRET || process.env.SHIPZEN_OAUTH_CLIENT_SECRET;

if (githubClientId && githubClientSecret) {
  providers.push(
    GitHubProvider({
      clientId: githubClientId,
      clientSecret: githubClientSecret,
    })
  )
} else if (process.env.ENABLE_LOCAL_STUB_AUTH === "true") {
  // Local Dev / Missing Auth0 fallback
  providers.push(
    CredentialsProvider({
      name: "Stub Auth",
      credentials: {
        username: { label: "Username", type: "text", placeholder: "admin" },
      },
      async authorize(credentials) {
        return {
          id: "local-dev-user",
          name: (credentials as Record<string, string>)?.username || "Local Admin",
          email: "admin@shipzen.local",
          image: "https://api.dicebear.com/7.x/avataaars/svg?seed=admin"
        }
      }
    })
  )
}

type Token = Record<string, unknown>

// Same resolution as the /api/proxy route: in-cluster service, else API_URL.
const API_BASE = process.env.KUBERNETES_SERVICE_HOST
  ? "http://shipzen-api.shipzen-system.svc.cluster.local:80"
  : (process.env.API_URL ?? "http://localhost:8000")

// Exchange the refresh token for a new access token (GitHub rotates both).
// On failure the session is marked with an error; middleware then sends the
// user back to the sign-in page instead of leaving them on a broken dashboard.
async function refreshGitHubToken(token: Token): Promise<Token> {
  if (!token.refreshToken || !githubClientId || !githubClientSecret) {
    return { ...token, error: "RefreshTokenError" }
  }
  try {
    const res = await fetch("https://github.com/login/oauth/access_token", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: githubClientId,
        client_secret: githubClientSecret,
        grant_type: "refresh_token",
        refresh_token: token.refreshToken,
      }),
    })
    const data = await res.json()
    if (!res.ok || data.error || !data.access_token) throw new Error(data.error || String(res.status))
    return {
      ...token,
      accessToken: data.access_token,
      refreshToken: data.refresh_token ?? token.refreshToken,
      expiresAt: data.expires_in ? Math.floor(Date.now() / 1000) + Number(data.expires_in) : undefined,
      error: undefined,
    }
  } catch (e) {
    console.error("GitHub token refresh failed:", e)
    return { ...token, error: "RefreshTokenError" }
  }
}

// Ask the API whether this GitHub token belongs to someone allowed in
// (allowlist or invitation). Anything but a 200 means no.
async function apiAcceptsToken(accessToken?: string): Promise<boolean> {
  if (!accessToken) return false
  try {
    const res = await fetch(`${API_BASE}/users/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    })
    return res.ok
  } catch (e) {
    console.error("Sign-in check against the API failed:", e)
    return false
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers,
  secret: process.env.AUTH_SECRET || process.env.SHIPZEN_AUTH_SECRET,
  trustHost: true,
  callbacks: {
    // Invite-only. A login on ALLOWED_GITHUB_USERS (comma-separated, same list
    // as the API) is let in straight away. Anyone else is let in only if the
    // API accepts their GitHub token: that's where admin invitations live
    // (POST /admin/invitations), and the API re-checks on every request anyway.
    // Fails closed: if the API says no or can't be reached, no session.
    async signIn({ account, profile }) {
      if (account?.provider !== "github") return true
      const allowed = (process.env.ALLOWED_GITHUB_USERS || "")
        .split(",").map((u) => u.trim().toLowerCase()).filter(Boolean)
      const login = String((profile as { login?: string } | undefined)?.login || "").toLowerCase()
      if (login && allowed.includes(login)) return true
      if (allowed.length === 0 &&
          (process.env.NODE_ENV === "development" || process.env.ALLOW_OPEN_SIGNUP === "true")) {
        return true
      }
      return apiAcceptsToken(account.access_token)
    },
    async jwt({ token, account }) {
      if (account) {
        token.accessToken = account.access_token || "stub-token"
        // GitHub App user tokens expire after 8 hours. Keep what we need to
        // refresh them; without this every session broke 8 hours after sign-in
        // (the UI stayed "logged in" while every API call returned 401).
        token.refreshToken = account.refresh_token
        token.expiresAt = account.expires_at // seconds since epoch
        delete token.error
        return token
      }
      const expiresAt = token.expiresAt as number | undefined
      if (!expiresAt || Date.now() < (expiresAt - 60) * 1000) return token
      return refreshGitHubToken(token)
    },
    async session({ session, token }) {
      // @ts-expect-error custom property
      session.accessToken = token.accessToken
      // @ts-expect-error custom property
      session.error = token.error
      return session
    },
  },
  pages: {
    signIn: "/",
    // Send sign-in errors back to the landing page, which explains them.
    // (The default Auth.js error page's "Sign in" link went to a broken URL.)
    error: "/",
  },
})
