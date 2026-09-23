import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { resetMutation } from '../api/@tanstack/react-query.gen'
import { resetInfo } from '../api/sdk.gen'
import { ErrorNotice, Field, Form, Notice, PASSWORD_HINT } from '../components/Form'
import { PublicPage, useFragmentToken } from '../components/Page'
import { errorMessage, fieldErrors } from '../lib/api'

export default function Reset() {
  const token = useFragmentToken()
  const link = useQuery({
    queryKey: ['reset', token],
    queryFn: async () => (await resetInfo({ body: { token } })).data,
    retry: false,
  })
  const [password, setPassword] = useState('')
  const save = useMutation(resetMutation())

  if (save.isSuccess) {
    return (
      <PublicPage title="Password changed">
        <p className="lede">You've been signed out on every device. Sign in with your new password.</p>
        <Link to="/login" className="button">
          Sign in
        </Link>
      </PublicPage>
    )
  }

  return (
    <PublicPage title="Choose a new password">
      {link.isError && <Notice tone="error">{errorMessage(link.error)}</Notice>}
      {link.data && (
        <Form onSubmit={() => save.mutate({ body: { token, password } })} error={save.error} className="stack">
          <Field
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => {
              setPassword(e.target.value)
              save.reset()
            }}
            hint={PASSWORD_HINT}
            error={fieldErrors(save.error).password}
          />
          <ErrorNotice error={save.error} />
          <button type="submit" disabled={save.isPending}>
            Save password
          </button>
        </Form>
      )}
    </PublicPage>
  )
}
