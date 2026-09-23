import { lazy } from 'react'
import { Link, type RouteObject } from 'react-router'
import { PublicPage } from '../components/Page'
import Daily from './Daily'
import Home from './Home'
import Invite from './Invite'
import Layout from './Layout'
import Login from './Login'
import Mock, { MockRun } from './Mock'
import Practice from './Practice'
import Profile from './Profile'
import Reset from './Reset'

// The admin area is only for a handful of people: keep it out of the main bundle.
const Admin = lazy(() => import('./Admin'))

function Crashed() {
  return (
    <PublicPage title="Something went wrong">
      <p>The page failed to load. Reloading usually fixes it; if not, tell a team admin.</p>
      <button type="button" onClick={() => window.location.reload()}>
        Reload
      </button>
    </PublicPage>
  )
}

function NotFound() {
  return (
    <PublicPage title="Page not found">
      <p>
        <Link to="/">Back to the start</Link>
      </p>
    </PublicPage>
  )
}

export const routes: RouteObject[] = [
  { path: '/login', element: <Login /> },
  { path: '/invite', element: <Invite /> },
  { path: '/reset', element: <Reset /> },
  {
    element: <Layout />,
    errorElement: <Crashed />,
    children: [
      { index: true, element: <Home /> },
      { path: 'daily', element: <Daily /> },
      { path: 'practice', element: <Practice /> },
      { path: 'mock', element: <Mock /> },
      { path: 'mock/:sessionId', element: <MockRun /> },
      { path: 'profile', element: <Profile /> },
      { path: 'admin', element: <Admin /> },
    ],
  },
  { path: '*', element: <NotFound /> },
]
