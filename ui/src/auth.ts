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

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers,
  secret: process.env.AUTH_SECRET || process.env.SHIPZEN_AUTH_SECRET,
  trustHost: true,
  callbacks: {
    // Invite-only: refuse GitHub sign-in for logins not in ALLOWED_GITHUB_USERS
    // (comma-separated). The API enforces the same list; this stops strangers
    // getting a session at all. Unset = open (local development).
    async signIn({ account, profile }) {
      const allowed = (process.env.ALLOWED_GITHUB_USERS || "")
        .split(",").map((u) => u.trim().toLowerCase()).filter(Boolean)
      if (allowed.length === 0 || account?.provider !== "github") return true
      const login = String((profile as { login?: string } | undefined)?.login || "").toLowerCase()
      return allowed.includes(login)
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
  },
})
