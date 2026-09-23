import { type ComponentProps, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, useId } from 'react'
import { errorMessage, fieldErrors } from '../lib/api'

export const PASSWORD_HINT = 'At least 10 characters. A few random words work well.'

export function Form({ onSubmit, ...props }: Omit<ComponentProps<'form'>, 'onSubmit'> & { onSubmit: () => void }) {
  return (
    <form
      noValidate
      {...props}
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
    />
  )
}

type Described = { label: string; hint?: ReactNode; error?: string }

function useDescribed({ hint, error }: Described) {
  const id = useId()
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  const extra = (
    <>
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </>
  )
  return { id, describedBy, extra }
}

export function Field({ label, hint, error, ...input }: Described & InputHTMLAttributes<HTMLInputElement>) {
  const { id, describedBy, extra } = useDescribed({ label, hint, error })
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} aria-invalid={!!error} aria-describedby={describedBy} {...input} />
      {extra}
    </div>
  )
}

export function SelectField({
  label,
  hint,
  error,
  children,
  ...select
}: Described & SelectHTMLAttributes<HTMLSelectElement>) {
  const { id, describedBy, extra } = useDescribed({ label, hint, error })
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} aria-invalid={!!error} aria-describedby={describedBy} {...select}>
        {children}
      </select>
      {extra}
    </div>
  )
}

export function Notice({ tone, children }: { tone: 'error' | 'ok'; children: ReactNode }) {
  return (
    <div className={`notice ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  )
}

/** A form-level error; errors tied to specific fields are shown next to those fields instead. */
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error || Object.keys(fieldErrors(error)).length) return null
  return <Notice tone="error">{errorMessage(error)}</Notice>
}
