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
      }
      return token
    },
    async session({ session, token }) {
      // @ts-expect-error custom property
      session.accessToken = token.accessToken
      return session
    },
  },
  pages: {
    signIn: "/",
  },
})
