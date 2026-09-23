import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { changePasswordMutation, logoutMutation, updateMeMutation } from '../api/@tanstack/react-query.gen'
import { type Me, Vertical } from '../api/types.gen'
import { ErrorNotice, Field, Form, Notice, PASSWORD_HINT, SelectField, useFieldErrors } from '../components/Form'
import { LevelCard } from '../components/LevelCard'
import { RankRoad } from '../components/RankRoad'
import { Page } from '../components/Page'
import { ME_KEY, queryClient, useMe } from '../lib/api'
import { POSITION_NAMES } from '../lib/xp'

export default function Profile() {
  const { data: user } = useMe()
  const navigate = useNavigate()
  const signOut = useMutation({
    ...logoutMutation(),
    onSettled: () => {
      queryClient.clear()
      navigate('/login')
    },
  })
  if (!user) return null
  return (
    <Page title="Profile" eyebrow="Your account">
      <p className="muted">Signed in as {user.email}</p>
      <LevelCard me={user} road={false} />
      <RankRoad me={user} />
      <ProfileForm user={user} />
      <PasswordForm />
      <section className="panel" aria-label="Session">
        <button type="button" className="secondary" onClick={() => signOut.mutate({})}>
          Sign out
        </button>
      </section>
    </Page>
  )
}

function ProfileForm({ user }: { user: Me }) {
  const [form, setForm] = useState({
    display_name: user.display_name,
    vertical: user.vertical ?? '',
    leaderboard_opt_out: user.leaderboard_opt_out,
  })
  const save = useMutation({
    ...updateMeMutation(),
    onSuccess: (me) => queryClient.setQueryData(ME_KEY, me),
  })
  const { errors, touch } = useFieldErrors(save.error)
  const edit = (patch: Partial<typeof form>) => {
    setForm({ ...form, ...patch })
    Object.keys(patch).forEach(touch)
    if (save.isSuccess) save.reset()
  }
  const submit = () => save.mutate({ body: { ...form, vertical: (form.vertical || null) as Vertical | null } })

  return (
    <Form onSubmit={submit} error={save.error} className="stack panel" aria-labelledby="profile-title">
      <h2 id="profile-title">How others see you</h2>
      <Field
        label="Display name"
        required
        maxLength={24}
        value={form.display_name}
        onChange={(e) => edit({ display_name: e.target.value })}
        error={errors.display_name}
      />
      <SelectField
        label="Vertical"
        value={form.vertical}
        onChange={(e) => edit({ vertical: e.target.value })}
        hint="Counts towards your vertical's average on the leaderboard."
        error={errors.vertical}
      >
        <option value="">Not set</option>
        {Object.values(Vertical).map((v) => (
          <option key={v}>{v}</option>
        ))}
      </SelectField>
      <p className="position">
        <strong>Position on the team:</strong> {POSITION_NAMES[user.position]}.{' '}
        <span className="muted">Only an admin can change it.</span>
      </p>
      <label className="check">
        <input
          type="checkbox"
          checked={form.leaderboard_opt_out}
          onChange={(e) => edit({ leaderboard_opt_out: e.target.checked })}
        />
        Hide me from the leaderboard (you still see your own rank)
      </label>
      <ErrorNotice error={save.error} />
      {save.isSuccess && <Notice tone="ok">Saved.</Notice>}
      <button type="submit" disabled={save.isPending}>
        Save profile
      </button>
    </Form>
  )
}

function PasswordForm() {
  const empty = { current_password: '', new_password: '' }
  const [form, setForm] = useState(empty)
  const save = useMutation({ ...changePasswordMutation(), onSuccess: () => setForm(empty) })
  const { errors, touch } = useFieldErrors(save.error)
  const edit = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm({ ...form, [key]: e.target.value })
    touch(key)
    if (save.isSuccess) save.reset()
  }

  return (
    <Form
      onSubmit={() => save.mutate({ body: form })}
      error={save.error}
      className="stack panel"
      aria-labelledby="password-title"
    >
      <h2 id="password-title">Password</h2>
      <Field
        label="Current password"
        type="password"
        autoComplete="current-password"
        required
        value={form.current_password}
        onChange={edit('current_password')}
        error={errors.current_password}
      />
      <Field
        label="New password"
        type="password"
        autoComplete="new-password"
        required
        value={form.new_password}
        onChange={edit('new_password')}
        hint={PASSWORD_HINT}
        error={errors.new_password}
      />
      <ErrorNotice error={save.error} />
      {save.isSuccess && <Notice tone="ok">Password changed. Other devices were signed out.</Notice>}
      <button type="submit" disabled={save.isPending}>
        Change password
      </button>
    </Form>
  )
}
