import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { NavLink, Outlet, useSearchParams } from "react-router-dom"
import { disconnectGoogle, googleStatus, startGoogle } from "../api/catalog"
import { messageOf } from "../api/client"

const links = [
  { to: "/sheet", label: "Sheet" },
  { to: "/profiles", label: "Profiles" },
  { to: "/resumes", label: "Resumes" },
  { to: "/templates", label: "Email Templates" },
]

const GOOGLE_ERRORS: Record<string, string> = {
  invalid_oauth_state: "The Google sign-in expired. Connect again.",
  oauth_exchange_failed: "Google did not accept the sign-in.",
  oauth_missing_refresh_token: "Google did not return a refresh token. Connect again.",
  oauth_missing_email: "Google did not return an email address.",
  oauth_not_configured: "Google sign-in is not configured.",
}

function navClass({ isActive }: { isActive: boolean }) {
  return `rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-stone-900 text-white" : "text-stone-700 hover:bg-stone-200"}`
}

export function Layout() {
  const queryClient = useQueryClient()
  const [params] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  const google = useQuery({ queryKey: ["google-status"], queryFn: googleStatus })
  const googleError = params.get("google_error")
  const notice = error ?? (googleError ? (GOOGLE_ERRORS[googleError] ?? "Google sign-in failed.") : null)

  async function connect() {
    setError(null)
    try {
      const started = await startGoogle()
      window.location.assign(started.authorization_url)
    } catch (caught) {
      setError(messageOf(caught))
    }
  }

  async function disconnect() {
    setError(null)
    try {
      await disconnectGoogle()
      await queryClient.invalidateQueries({ queryKey: ["google-status"] })
    } catch (caught) {
      setError(messageOf(caught))
    }
  }

  return (
    <div className="min-h-screen bg-stone-100 text-stone-900">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-4 sm:px-6">
          <p className="text-sm font-semibold tracking-tight">Outreach</p>
          <nav className="flex flex-1 flex-wrap gap-1">
            {links.map((link) => (
              <NavLink key={link.to} to={link.to} className={navClass}>
                {link.label}
              </NavLink>
            ))}
          </nav>
          {google.data?.connected ? (
            <div className="flex items-center gap-3">
              <p className="text-sm text-stone-600">{google.data.email}</p>
              <button type="button" className="btn-ghost" onClick={() => void disconnect()}>
                Disconnect
              </button>
            </div>
          ) : (
            <button type="button" className="btn" onClick={() => void connect()}>
              Connect Google
            </button>
          )}
        </div>
      </header>
      {notice ? <p className="mx-auto max-w-6xl px-4 pt-4 text-sm text-red-700 sm:px-6">{notice}</p> : null}
      {params.get("google") === "connected" && google.data?.connected ? (
        <p className="mx-auto max-w-6xl px-4 pt-4 text-sm text-stone-600 sm:px-6">Google is connected.</p>
      ) : null}
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <Outlet />
      </main>
    </div>
  )
}
