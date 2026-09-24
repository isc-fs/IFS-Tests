import { type ReactNode, useEffect, useRef, useState } from 'react'
import { Link, NavLink } from 'react-router'

export const APP_NAME = 'MingoQuiz'

/** Sets the tab title and moves focus to the heading, so screen readers announce the new page. */
export function Page({
  title,
  heading,
  eyebrow,
  children,
}: {
  title: string
  heading?: string
  eyebrow?: string
  children: ReactNode
}) {
  const h1 = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    document.title = `${title} · ${APP_NAME}`
    // A link to a section (/profile#your-data) lands there; the section takes focus itself.
    if (!document.getElementById(window.location.hash.slice(1))) h1.current?.focus()
  }, [title])
  return (
    <>
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      <h1 ref={h1} tabIndex={-1}>
        {heading ?? title}
      </h1>
      {children}
    </>
  )
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="shell isc-light">
      {children}
      <footer className="footer">
        <p>
          Questions from <a href="https://fs-quiz.eu">FS-Quiz</a> (Yannik Ottens), licensed under the{' '}
          <a href="https://opendatacommons.org/licenses/odbl/">ODbL</a>.
        </p>
        <nav aria-label="About this site">
          <NavLink to="/about">About</NavLink>
          <NavLink to="/privacy">Privacy</NavLink>
        </nav>
      </footer>
    </div>
  )
}

export function Brand() {
  return (
    <Link to="/" className="brand">
      {APP_NAME}
    </Link>
  )
}

/** Pages shown to signed-out visitors: sign-in, invite, reset, not found; `wide` for reading (privacy, about). */
export function PublicPage({
  title,
  heading,
  wide,
  children,
}: {
  title: string
  heading?: string
  wide?: boolean
  children: ReactNode
}) {
  return (
    <Shell>
      <header className="topbar">
        <Brand />
      </header>
      <main className={`content stack${wide ? '' : ' narrow'}`}>
        <Page title={title} heading={heading}>
          {children}
        </Page>
      </main>
    </Shell>
  )
}

/** Invite and reset tokens travel in the URL fragment, which browsers never send to a server.
 *  Read it once, then drop it from the address bar and history. */
export function useFragmentToken(): string {
  const [token] = useState(() => window.location.hash.slice(1))
  useEffect(() => {
    const { pathname, search, hash } = window.location
    if (hash) window.history.replaceState(window.history.state, '', pathname + search)
  }, [])
  return token
}
