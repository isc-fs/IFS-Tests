import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { inviteInfo, register } from '../api/sdk.gen'
import { Field, Notice, PASSWORD_HINT } from '../components/Form'
import { errorMessage } from '../lib/api'
import { Brand, Shell } from './Layout'

export default function Invite() {
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const invite = useQuery({ queryKey: ['invite', token], queryFn: async () => (await inviteInfo({ path: { token } })).data, retry: false })
  const [form, setForm] = useState({ email: '', display_name: '', password: '' })
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value })

  const join = useMutation({
    mutationFn: () => register({ body: { token, ...form } }),
    onSuccess: ({ data }) => {
      queryClient.setQueryData(['me'], data)
      navigate('/', { replace: true })
    },
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    join.mutate()
  }

  return (
    <Shell>
      <header className="topbar"><Brand /></header>
      <main className="content narrow">
        <h1>Join IFS-Tests</h1>
        {invite.isPending && <p className="muted">Checking your invite…</p>}
        {invite.isError && <Notice tone="error">{errorMessage(invite.error)}</Notice>}
        {invite.data && (
          <>
            <p className="lede">
              You've been invited{invite.data.vertical ? ` to the ${invite.data.vertical} vertical` : ''}. Pick how you'll sign in and how others see you.
            </p>
            <form onSubmit={submit} className="stack">
              <Field label="Email" name="email" type="email" autoComplete="email" required value={form.email} onChange={set('email')} hint="Only admins see it. You'll use it to sign in." />
              <Field label="Display name" name="display_name" autoComplete="nickname" required minLength={2} maxLength={24} value={form.display_name} onChange={set('display_name')} hint="Shown on the leaderboard. You can hide yourself later." />
              <Field label="Password" name="password" type="password" autoComplete="new-password" required minLength={10} value={form.password} onChange={set('password')} hint={PASSWORD_HINT} />
              {join.isError && <Notice tone="error">{errorMessage(join.error)}</Notice>}
              <button type="submit" disabled={join.isPending}>{join.isPending ? 'Creating account…' : 'Create account'}</button>
            </form>
          </>
        )}
      </main>
    </Shell>
  )
}
