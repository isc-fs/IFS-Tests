import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router'
import { login } from '../api/sdk.gen'
import { Field, Notice } from '../components/Form'
import { errorMessage, useMe } from '../lib/api'
import { Brand, Shell } from './Layout'

/** Only same-app paths, so a crafted ?next= can't send people to another site. */
export function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/'
}

export default function Login() {
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: user } = useMe()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const signIn = useMutation({
    mutationFn: () => login({ body: { email, password } }),
    onSuccess: ({ data }) => {
      queryClient.setQueryData(['me'], data)
      navigate(next, { replace: true })
    },
  })

  if (user) return <Navigate to={next} replace />

  const submit = (e: FormEvent) => {
    e.preventDefault()
    signIn.mutate()
  }

  return (
    <Shell>
      <header className="topbar"><Brand /></header>
      <main className="content narrow">
        <h1>Sign in</h1>
        <form onSubmit={submit} className="stack">
          <Field label="Email" name="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <Field label="Password" name="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          {signIn.isError && <Notice tone="error">{errorMessage(signIn.error)}</Notice>}
          <button type="submit" disabled={signIn.isPending}>{signIn.isPending ? 'Signing in…' : 'Sign in'}</button>
        </form>
        <p className="muted">
          New here? You need an invite link from a team admin. Forgot your password? Ask an admin for a reset link.
        </p>
      </main>
    </Shell>
  )
}
