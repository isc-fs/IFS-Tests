import { Suspense } from 'react'
import { Navigate, NavLink, Outlet, useLocation } from 'react-router'
import { Notice } from '../components/Form'
import { Brand, Shell } from '../components/Page'
import { consumeSessionEnded, useMe } from '../lib/api'

/** Frame for pages that need a signed-in member. */
export default function Layout() {
  const { data: user, isPending, isError, error, refetch } = useMe()
  const location = useLocation()

  if (isPending) {
    return (
      <Shell>
        <main className="content" aria-busy="true" />
      </Shell>
    )
  }
  if (isError) {
    return (
      <Shell>
        <main className="content narrow stack">
          <Notice tone="error">{error.message} Your session is still there; try again in a moment.</Notice>
          <button type="button" onClick={() => refetch()}>
            Try again
          </button>
        </main>
      </Shell>
    )
  }
  if (!user) {
    const expired = consumeSessionEnded() ? '&expired=1' : ''
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}${expired}`} replace />
  }

  return (
    <Shell>
      <header className="topbar">
        <Brand />
        <nav aria-label="Main">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/daily">Daily</NavLink>
          <NavLink to="/practice">Practice</NavLink>
          <NavLink to="/mock">Mock</NavLink>
          <NavLink to="/profile">Profile</NavLink>
          {user.role !== 'member' && <NavLink to="/review">Review</NavLink>}
          {user.role === 'admin' && <NavLink to="/admin">Admin</NavLink>}
        </nav>
      </header>
      <main className="content">
        <Suspense fallback={<p className="muted">Loading…</p>}>
          <Outlet />
        </Suspense>
      </main>
    </Shell>
  )
}
