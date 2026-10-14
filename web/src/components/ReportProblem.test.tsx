import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { queryClient } from '../lib/api'
import { ReportProblem } from './ReportProblem'

const HINT = 'Name the option by its text, not its letter.'
const OPEN = { name: 'Report a problem with this question' }

const mount = (nameByText?: boolean) =>
  render(
    <QueryClientProvider client={queryClient}>
      <ReportProblem questionId={5} nameByText={nameByText} />
    </QueryClientProvider>,
  )

test('the report form asks for the option by its text when the parent says letters differ between players', async () => {
  mount(true)
  expect(screen.queryByText(HINT)).toBeNull()
  await userEvent.click(screen.getByRole('button', OPEN))
  expect(screen.getByLabelText("What's wrong?")).toBeInTheDocument()
  expect(screen.getByText(HINT)).toBeInTheDocument()
})

test.each([[undefined], [false]])('without the prop (%s) the form does not mention letters at all', async (flag) => {
  mount(flag)
  await userEvent.click(screen.getByRole('button', OPEN))
  expect(screen.getByLabelText("What's wrong?")).toBeInTheDocument()
  expect(screen.queryByText(HINT)).toBeNull()
  expect(screen.queryByText(/letter/i)).toBeNull()
})

test('the hint goes away with the form', async () => {
  mount(true)
  await userEvent.click(screen.getByRole('button', OPEN))
  expect(screen.getByText(HINT)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /cancel|close/i }))
  expect(screen.queryByText(HINT)).toBeNull()
})

test('the existing examples stay with or without the hint', async () => {
  for (const flag of [true, undefined]) {
    const view = mount(flag)
    await userEvent.click(screen.getByRole('button', OPEN))
    expect(screen.getByText(/the official answer is wrong/)).toBeInTheDocument()
    view.unmount()
  }
})
