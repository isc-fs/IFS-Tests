import type { InputHTMLAttributes, ReactNode } from 'react'

type FieldProps = InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode }

export function Field({ label, hint, id, ...input }: FieldProps) {
  const inputId = id ?? input.name
  return (
    <div className="field">
      <label htmlFor={inputId}>{label}</label>
      <input id={inputId} {...input} />
      {hint && <p className="hint">{hint}</p>}
    </div>
  )
}

export function Notice({ tone, children }: { tone: 'error' | 'ok'; children: ReactNode }) {
  return (
    <p className={`notice ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </p>
  )
}

export const PASSWORD_HINT = 'At least 10 characters. A few random words work well.'
