import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'

afterEach(() => vi.restoreAllMocks())

test('shows the FS-Quiz attribution and the server status', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ status: 'ok', version: '0.2.0' }), { status: 200 }),
  )
  render(<App />)
  expect(screen.getByText('FS-Quiz')).toHaveAttribute('href', 'https://fs-quiz.eu')
  expect(await screen.findByText('Server ok · v0.2.0')).toBeInTheDocument()
})
