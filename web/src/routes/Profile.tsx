import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import type { Me } from '../api/types.gen'
import { changePassword, updateMe } from '../api/sdk.gen'
import { Field, Notice, PASSWORD_HINT } from '../components/Form'
import { errorMessage, useMe, VERTICALS } from '../lib/api'

export default function Profile() {
  const { data: user } = useMe()
  if (!user) return null
  return (
    <>
      <h1>Profile</h1>
      <ProfileForm user={user} />
      <PasswordForm />
    </>
  )
}

function ProfileForm({ user }: { user: Me }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(user.display_name)
  const [vertical, setVertical] = useState(user.vertical ?? '')
  const [optOut, setOptOut] = useState(user.leaderboard_opt_out)

  const save = useMutation({
    mutationFn: () =>
      updateMe({
        body: {
          display_name: name,
          vertical: (vertical || null) as Me['vertical'],
          clear_vertical: !vertical,
          leaderboard_opt_out: optOut,
        },
      }),
    onSuccess: ({ data }) => queryClient.setQueryData(['me'], data),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={submit} className="stack panel" aria-labelledby="profile-title">
      <h2 id="profile-title">How others see you</h2>
      <p className="muted">Signed in as {user.email}</p>
      <Field label="Display name" name="display_name" required minLength={2} maxLength={24} value={name} onChange={(e) => setName(e.target.value)} />
      <div className="field">
        <label htmlFor="vertical">Vertical</label>
        <select id="vertical" value={vertical} onChange={(e) => setVertical(e.target.value)}>
          <option value="">Not set</option>
          {VERTICALS.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <p className="hint">Counts towards your vertical's average on the leaderboard.</p>
      </div>
      <label className="check">
        <input type="checkbox" checked={optOut} onChange={(e) => setOptOut(e.target.checked)} />
        Hide me from the leaderboard (you still see your own rank)
      </label>
      {save.isError && <Notice tone="error">{errorMessage(save.error)}</Notice>}
      {save.isSuccess && <Notice tone="ok">Saved.</Notice>}
      <button type="submit" disabled={save.isPending}>Save profile</button>
    </form>
  )
}

function PasswordForm() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const save = useMutation({
    mutationFn: () => changePassword({ body: { current_password: current, new_password: next } }),
    onSuccess: () => {
      setCurrent('')
      setNext('')
    },
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={submit} className="stack panel" aria-labelledby="password-title">
      <h2 id="password-title">Password</h2>
      <Field label="Current password" name="current_password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
      <Field label="New password" name="new_password" type="password" autoComplete="new-password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} hint={PASSWORD_HINT} />
      {save.isError && <Notice tone="error">{errorMessage(save.error)}</Notice>}
      {save.isSuccess && <Notice tone="ok">Password changed. Other devices were signed out.</Notice>}
      <button type="submit" disabled={save.isPending}>Change password</button>
    </form>
  )
}
