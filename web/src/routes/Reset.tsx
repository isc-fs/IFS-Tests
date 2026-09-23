import { useMutation, useQuery } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, useParams } from 'react-router'
import { reset, resetInfo } from '../api/sdk.gen'
import { Field, Notice, PASSWORD_HINT } from '../components/Form'
import { errorMessage } from '../lib/api'
import { Brand, Shell } from './Layout'

export default function Reset() {
  const { token = '' } = useParams()
  const link = useQuery({ queryKey: ['reset', token], queryFn: async () => (await resetInfo({ path: { token } })).data, retry: false })
  const [password, setPassword] = useState('')
  const save = useMutation({ mutationFn: () => reset({ body: { token, password } }) })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <Shell>
      <header className="topbar"><Brand /></header>
      <main className="content narrow">
        <h1>Choose a new password</h1>
        {link.isError && <Notice tone="error">{errorMessage(link.error)}</Notice>}
        {save.isSuccess ? (
          <Notice tone="ok">
            Password changed. You've been signed out everywhere. <Link to="/login">Sign in</Link>
          </Notice>
        ) : (
          link.data && (
            <form onSubmit={submit} className="stack">
              <Field label="New password" name="password" type="password" autoComplete="new-password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} hint={PASSWORD_HINT} />
              {save.isError && <Notice tone="error">{errorMessage(save.error)}</Notice>}
              <button type="submit" disabled={save.isPending}>Save password</button>
            </form>
          )
        )}
      </main>
    </Shell>
  )
}
