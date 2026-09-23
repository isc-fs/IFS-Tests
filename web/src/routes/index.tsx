import { lazy } from 'react'
import type { RouteObject } from 'react-router'
import Home from './Home'
import Invite from './Invite'
import Layout, { Shell } from './Layout'
import Login from './Login'
import Profile from './Profile'
import Reset from './Reset'

// The admin area is only for a handful of people: keep it out of the main bundle.
const Admin = lazy(() => import('./Admin'))

function NotFound() {
  return (
    <Shell>
      <main className="content narrow">
        <h1>Page not found</h1>
        <p><a href="/">Back to the start</a></p>
      </main>
    </Shell>
  )
}

export const routes: RouteObject[] = [
  { path: '/login', element: <Login /> },
  { path: '/invite/:token', element: <Invite /> },
  { path: '/reset/:token', element: <Reset /> },
  {
    element: <Layout />,
    children: [
      { index: true, element: <Home /> },
      { path: 'profile', element: <Profile /> },
      { path: 'admin', element: <Admin /> },
    ],
  },
  { path: '*', element: <NotFound /> },
]
