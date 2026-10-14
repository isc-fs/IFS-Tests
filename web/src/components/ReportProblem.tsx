import { useMutation } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'
import { reportQuestionMutation } from '../api/@tanstack/react-query.gen'
import { ErrorNotice, Form, Notice, useFieldErrors } from './Form'

/** Lets a player tell reviewers that a question or its answer looks wrong. `nameByText`: the options may be in a
 * different order for each player, so the report should name an option by its text, not its letter. */
export function ReportProblem({ questionId, nameByText }: { questionId: number; nameByText?: boolean }) {
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')
  const id = useId()
  const send = useMutation(reportQuestionMutation())
  const { errors, touch } = useFieldErrors(send.error)
  const toggle = useRef<HTMLButtonElement>(null)
  const field = useRef<HTMLTextAreaElement>(null)
  const thanks = useRef<HTMLDivElement>(null)
  const moved = useRef(false)

  useEffect(() => {
    if (!moved.current) return
    if (send.isSuccess) thanks.current?.focus()
    else if (open) field.current?.focus()
    else toggle.current?.focus()
  }, [open, send.isSuccess])

  const show = (value: boolean) => {
    moved.current = true
    setOpen(value)
  }

  if (send.isSuccess) {
    return (
      <Notice tone="ok" ref={thanks} tabIndex={-1}>
        Thanks. A reviewer will take a look.
      </Notice>
    )
  }
  if (!open) {
    return (
      <p>
        <button type="button" ref={toggle} className="link-button" onClick={() => show(true)}>
          Report a problem with this question
        </button>
      </p>
    )
  }
  return (
    <Form
      onSubmit={() => send.mutate({ path: { question_id: questionId }, body: { message } })}
      error={send.error}
      className="stack report"
    >
      <div className="field">
        <label htmlFor={id}>What's wrong?</label>
        <textarea
          id={id}
          ref={field}
          rows={3}
          maxLength={500}
          value={message}
          onChange={(e) => {
            setMessage(e.target.value)
            touch('message')
          }}
          aria-invalid={!!errors.message}
          aria-describedby={[`${id}-hint`, nameByText && `${id}-letter`, errors.message && `${id}-error`]
            .filter(Boolean)
            .join(' ')}
        />
        <p className="hint" id={`${id}-hint`}>
          For example: the official answer is wrong, a figure is missing, or the rules have changed.
        </p>
        {nameByText && (
          <p className="hint" id={`${id}-letter`}>
            Name the option by its text, not its letter.
          </p>
        )}
        {errors.message && (
          <p className="field-error" id={`${id}-error`}>
            {errors.message}
          </p>
        )}
      </div>
      <ErrorNotice error={send.error} />
      <div className="row">
        <button type="submit" disabled={send.isPending || message.trim().length < 3}>
          Send report
        </button>
        <button type="button" className="secondary" onClick={() => show(false)}>
          Cancel
        </button>
      </div>
    </Form>
  )
}
