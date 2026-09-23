import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router'
import { loginMutation } from '../api/@tanstack/react-query.gen'
import { ErrorNotice, Field, Form, Notice } from '../components/Form'
import { PublicPage } from '../components/Page'
import { ME_KEY, queryClient, useMe } from '../lib/api'

/** Only paths inside this app, so a crafted ?next= can't send people to another site. */
export function safeNext(next: string | null): string {
  if (!next?.startsWith('/') || next.startsWith('//') || [...next].some((c) => c === '\\' || c < ' ')) return '/'
  return next
}

export default function Login() {
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const navigate = useNavigate()
  const { data: user } = useMe()
  const [form, setForm] = useState({ email: '', password: '' })
  const [missing, setMissing] = useState<Partial<Record<keyof typeof form, string>>>({})
  const signIn = useMutation({
    ...loginMutation(),
    onSuccess: (me) => {
      queryClient.setQueryData(ME_KEY, me)
      navigate(next, { replace: true })
    },
  })

  if (user) return <Navigate to={next} replace />

  const edit = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm({ ...form, [key]: e.target.value })
    setMissing({ ...missing, [key]: undefined })
    signIn.reset()
  }
  const submit = () => {
    const empty = {
      email: form.email.trim() ? undefined : 'Enter your email.',
      password: form.password ? undefined : 'Enter your password.',
    }
    setMissing(empty)
    if (!empty.email && !empty.password) signIn.mutate({ body: form })
  }

  return (
    <PublicPage title="Sign in">
      {params.get('expired') && <Notice tone="ok">Your session ended. Sign in to continue.</Notice>}
      <Form onSubmit={submit} error={missing.email || missing.password ? missing : signIn.error} className="stack">
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          required
          value={form.email}
          onChange={edit('email')}
          error={missing.email}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={form.password}
          onChange={edit('password')}
          error={missing.password}
        />
        <ErrorNotice error={signIn.error} />
        <button type="submit" disabled={signIn.isPending}>
          {signIn.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </Form>
      <p className="muted">
        New here? You need an invite link from a team admin. Forgot your password? Ask an admin for a reset link.
      </p>
    </PublicPage>
  )
}
