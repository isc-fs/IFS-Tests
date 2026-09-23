import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { registerMutation } from '../api/@tanstack/react-query.gen'
import { inviteInfo } from '../api/sdk.gen'
import { Vertical } from '../api/types.gen'
import { ErrorNotice, Field, Form, Notice, PASSWORD_HINT, SelectField, useFieldErrors } from '../components/Form'
import { PublicPage, useFragmentToken } from '../components/Page'
import { errorMessage, ME_KEY, queryClient } from '../lib/api'

export default function Invite() {
  const token = useFragmentToken()
  const navigate = useNavigate()
  const invite = useQuery({
    queryKey: ['invite', token],
    queryFn: async () => (await inviteInfo({ body: { token } })).data,
    retry: false,
  })
  const [form, setForm] = useState({ email: '', display_name: '', password: '', vertical: '' })
  const join = useMutation({
    ...registerMutation(),
    onSuccess: (me) => {
      queryClient.setQueryData(ME_KEY, me)
      navigate('/', { replace: true })
    },
  })
  const { errors, touch } = useFieldErrors(join.error)
  const edit = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setForm({ ...form, [key]: e.target.value })
    touch(key)
  }
  const submit = () => join.mutate({ body: { token, ...form, vertical: (form.vertical || null) as Vertical | null } })

  return (
    <PublicPage title="Join" heading="Join IFS-Tests">
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
            <ErrorNotice error={join.error} />
            <button type="submit" disabled={join.isPending}>
              {join.isPending ? 'Creating account…' : 'Create account'}
            </button>
          </Form>
        </>
      )}
    </PublicPage>
  )
}
