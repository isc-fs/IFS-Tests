import {
  type ComponentProps,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react'
import { errorMessage, fieldErrors } from '../lib/api'

export const PASSWORD_HINT = 'At least 10 characters. A few random words work well.'

/** Submits without a page reload; after a failed submit, focus goes to the first field in error. */
export function Form({
  onSubmit,
  error,
  ...props
}: Omit<ComponentProps<'form'>, 'onSubmit'> & { onSubmit: () => void; error?: unknown }) {
  const form = useRef<HTMLFormElement>(null)
  const submitted = useRef(false)
  useEffect(() => {
    if (!error || !submitted.current) return
    submitted.current = false
    form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
  }, [error])
  return (
    <form
      ref={form}
      noValidate
      {...props}
      onSubmit={(e) => {
        e.preventDefault()
        submitted.current = true
        onSubmit()
      }}
    />
  )
}

/** Server field errors that disappear one by one as the user edits those fields. */
export function useFieldErrors(error: unknown) {
  const [edited, setEdited] = useState<{ error: unknown; fields: Set<string> }>({ error, fields: new Set() })
  const fields = edited.error === error ? edited.fields : new Set<string>()
  const all = fieldErrors(error)
  const errors = Object.fromEntries(Object.entries(all).filter(([k]) => !fields.has(k)))
  const touch = (field: string) => setEdited({ error, fields: new Set([...fields, field]) })
  return { errors, touch }
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
