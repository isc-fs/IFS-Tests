import { useQueryClient } from '@tanstack/react-query'
import { Suspense } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router'
import { logout } from '../api/sdk.gen'
import { useMe } from '../lib/api'

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell isc-light">
      {children}
      <footer className="footer">
        Questions from <a href="https://fs-quiz.eu">FS-Quiz</a> (Yannik Ottens), licensed under the{' '}
        <a href="https://opendatacommons.org/licenses/odbl/">ODbL</a>.
      </footer>
    </div>
  )
}

export function Brand() {
  return (
    <Link to="/" className="brand">
      IFS-Tests
    </Link>
  )
}

/** Pages that need a signed-in member. */
export default function Layout() {
  const { data: user, isPending } = useMe()
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  if (isPending) return <Shell><main className="content" aria-busy="true" /></Shell>
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />

  const signOut = async () => {
    await logout()
    queryClient.clear()
    navigate('/login')
  }

  return (
    <Shell>
      <header className="topbar">
        <Brand />
        <nav aria-label="Main">
          <NavLink to="/" end>Home</NavLink>
          <NavLink to="/profile">Profile</NavLink>
          {user.role === 'admin' && <NavLink to="/admin">Admin</NavLink>}
        </nav>
        <button type="button" className="link-button" onClick={signOut}>
          Sign out
        </button>
      </header>
      <main className="content">
        <Suspense fallback={<p className="muted">Loading…</p>}>
          <Outlet />
        </Suspense>
      </main>
    </Shell>
  )
}
