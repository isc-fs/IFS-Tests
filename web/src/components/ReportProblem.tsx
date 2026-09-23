import { useMutation } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { reportQuestionMutation } from '../api/@tanstack/react-query.gen'
import { ErrorNotice, Form, Notice } from './Form'

/** Lets a player tell reviewers that a question or its answer looks wrong. */
export function ReportProblem({ questionId }: { questionId: number }) {
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')
  const id = useId()
  const send = useMutation(reportQuestionMutation())

  if (send.isSuccess) return <Notice tone="ok">Thanks. A reviewer will take a look.</Notice>
  if (!open) {
    return (
      <p>
        <button type="button" className="link-button" onClick={() => setOpen(true)}>
          Report a problem with this question
        </button>
      </p>
    )
  }
  return (
    <Form
      onSubmit={() => send.mutate({ path: { question_id: questionId }, body: { message } })}
      className="stack report"
    >
      <div className="field">
        <label htmlFor={id}>What's wrong?</label>
        <textarea
          id={id}
          rows={3}
          maxLength={500}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          aria-describedby={`${id}-hint`}
        />
        <p className="hint" id={`${id}-hint`}>
          For example: the official answer is wrong, a figure is missing, or the rules have changed.
        </p>
      </div>
      <ErrorNotice error={send.error} />
      <div className="row">
        <button type="submit" disabled={send.isPending || message.trim().length < 3}>
          Send report
        </button>
        <button type="button" className="secondary" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </Form>
  )
}
