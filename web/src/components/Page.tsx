import { type ReactNode, useEffect, useRef } from 'react'
import { Link } from 'react-router'

/** Sets the tab title and moves focus to the heading, so screen readers announce the new page. */
export function Page({ title, heading, children }: { title: string; heading?: string; children: ReactNode }) {
  const h1 = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    document.title = `${title} · IFS-Tests`
    h1.current?.focus()
  }, [title])
  return (
    <>
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

/** Pages shown to signed-out visitors: sign-in, invite, reset, not found. */
export function PublicPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Shell>
      <header className="topbar">
        <Brand />
      </header>
      <main className="content narrow">
        <Page title={title}>{children}</Page>
      </main>
    </Shell>
  )
}

/** Invite and reset tokens travel in the URL fragment, which browsers never send to a server. */
export function tokenFromHash(): string {
  return window.location.hash.slice(1)
}
