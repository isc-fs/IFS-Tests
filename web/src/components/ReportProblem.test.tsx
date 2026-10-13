import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { queryClient } from '../lib/api'
import { ReportProblem } from './ReportProblem'

const mount = () =>
  render(
    <QueryClientProvider client={queryClient}>
      <ReportProblem questionId={5} />
    </QueryClientProvider>,
  )

test('the report form asks for the option by its text, because letters differ between players', async () => {
  mount()
  expect(screen.queryByText('Name the option by its text, not its letter.')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Report a problem with this question' }))
  expect(screen.getByLabelText("What's wrong?")).toBeInTheDocument()
  expect(screen.getByText('Name the option by its text, not its letter.')).toBeInTheDocument()
})

test('the existing examples stay beside the new line', async () => {
  mount()
  await userEvent.click(screen.getByRole('button', { name: 'Report a problem with this question' }))
  expect(screen.getByText(/the official answer is wrong/)).toBeInTheDocument()
})
