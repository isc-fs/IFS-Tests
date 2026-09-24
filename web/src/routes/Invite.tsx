import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { registerMutation } from '../api/@tanstack/react-query.gen'
import { inviteInfo } from '../api/sdk.gen'
import { type Position, Vertical } from '../api/types.gen'
import { ErrorNotice, Field, Form, Notice, PASSWORD_HINT, SelectField, useFieldErrors } from '../components/Form'
import { PublicPage, useFragmentToken } from '../components/Page'
import { COOKIE_REFUSED, errorMessage, sessionWorks } from '../lib/api'
import { POSITIONS } from '../lib/xp'

export default function Invite() {
  const token = useFragmentToken()
  const navigate = useNavigate()
  const invite = useQuery({
    queryKey: ['invite', token],
    queryFn: async () => (await inviteInfo({ body: { token } })).data,
    retry: false,
  })
  const [form, setForm] = useState({ email: '', display_name: '', password: '', vertical: '', position: 'mingo' })
  const [refused, setRefused] = useState(false)
  const join = useMutation({
    ...registerMutation(),
    onSuccess: async () => {
      if (await sessionWorks()) navigate('/', { replace: true })
      else setRefused(true)
    },
  })
  const { errors, touch } = useFieldErrors(join.error)
  const edit = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setForm({ ...form, [key]: e.target.value })
    touch(key)
  }
  const submit = () =>
    join.mutate({
      body: {
        token,
        ...form,
        vertical: (form.vertical || null) as Vertical | null,
        position: form.position as Position,
      },
    })

  return (
    <PublicPage title="Join" heading="Join MingoQuiz">
      {invite.isPending && <p className="muted">Checking your invite…</p>}
      {invite.isError && (
        <>
          <Notice tone="error">{errorMessage(invite.error)}</Notice>
          <p>
            Already joined? <Link to="/login">Sign in</Link>
          </p>
        </>
      )}
      {invite.data && (
        <>
          <p className="lede">
            You've been invited{invite.data.vertical ? ` to the ${invite.data.vertical} vertical` : ''}. Choose how
            you'll sign in and how others see you.
          </p>
          <Form onSubmit={submit} error={join.error} className="stack">
            <Field
              label="Email"
              type="email"
              autoComplete="email"
              required
              value={form.email}
              onChange={edit('email')}
              hint="Only admins see it. You'll use it to sign in."
              error={errors.email}
            />
            <Field
              label="Display name"
              autoComplete="nickname"
              required
              maxLength={24}
              value={form.display_name}
              onChange={edit('display_name')}
              hint="Shown on the leaderboard. You can hide yourself later."
              error={errors.display_name}
            />
            {!invite.data.vertical && (
              <SelectField label="Vertical" value={form.vertical} onChange={edit('vertical')} error={errors.vertical}>
                <option value="">Choose later</option>
                {Object.values(Vertical).map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </SelectField>
            )}
            <SelectField
              label="Where are you on the team?"
              value={form.position}
              onChange={edit('position')}
              hint="It places you on the ladder: higher positions start higher, with less help and more at stake. Only an admin can change it later."
              error={errors.position}
            >
              {Object.entries(POSITIONS).map(([r, label]) => (
                <option key={r} value={r}>
                  {label}
                </option>
              ))}
            </SelectField>
            <Field
              label="Password"
              type="password"
              autoComplete="new-password"
              required
              value={form.password}
              onChange={edit('password')}
              hint={PASSWORD_HINT}
              error={errors.password}
            />
            <p className="muted">
              Your answers and XP are kept while you&apos;re on the team; you can download or delete them any time.{' '}
              <Link to="/privacy">How we handle your data</Link>
            </p>
            <ErrorNotice error={join.error} />
            {refused && <Notice tone="error">{COOKIE_REFUSED}</Notice>}
            <button type="submit" disabled={join.isPending}>
              {join.isPending ? 'Creating account…' : 'Create account'}
            </button>
          </Form>
        </>
      )}
    </PublicPage>
  )
}
