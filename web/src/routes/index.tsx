import { lazy, Suspense } from 'react'
import { Link, type RouteObject } from 'react-router'
import { PublicPage } from '../components/Page'
import Daily from './Daily'
import Home from './Home'
import Invite from './Invite'
import Layout from './Layout'
import Leaderboard from './Leaderboard'
import Login from './Login'
import Mock, { MockRun } from './Mock'
import Practice from './Practice'
import Profile from './Profile'
import Reset from './Reset'

// The admin and review areas are only for a handful of people: keep them out of the main bundle.
const Admin = lazy(() => import('./Admin'))
const About = lazy(() => import('./About').then((m) => ({ default: m.About })))
const Privacy = lazy(() => import('./About').then((m) => ({ default: m.Privacy })))
const Review = lazy(() => import('./Review'))
const ReviewDetail = lazy(() => import('./Review').then((m) => ({ default: m.ReviewDetail })))
// Live sessions: their own bundle, with the QR encoder.
const Live = lazy(() => import('./Live'))
const LiveSession = lazy(() => import('./Live').then((m) => ({ default: m.LiveSession })))
const LiveScreen = lazy(() => import('./Live').then((m) => ({ default: m.LiveScreen })))

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
    path: '/about',
    errorElement: <Crashed />,
    element: (
      <Suspense fallback={null}>
        <About />
      </Suspense>
    ),
  },
  {
    path: '/privacy',
    errorElement: <Crashed />,
    element: (
      <Suspense fallback={null}>
        <Privacy />
      </Suspense>
    ),
  },
  {
    element: <Layout />,
    errorElement: <Crashed />,
    children: [
      { index: true, element: <Home /> },
      { path: 'daily', element: <Daily /> },
      { path: 'practice', element: <Practice /> },
      { path: 'mock', element: <Mock /> },
      { path: 'mock/:sessionId', element: <MockRun /> },
      { path: 'leaderboard', element: <Leaderboard /> },
      { path: 'profile', element: <Profile /> },
      { path: 'admin', element: <Admin /> },
      { path: 'review', element: <Review /> },
      { path: 'review/:questionId', element: <ReviewDetail /> },
      { path: 'live', element: <Live /> },
      { path: 'live/:code', element: <LiveSession /> },
      { path: 'live/:code/screen', element: <LiveScreen /> },
    ],
  },
  { path: '*', element: <NotFound /> },
]
