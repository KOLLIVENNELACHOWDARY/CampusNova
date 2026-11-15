import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { errorMessage } from '../api'
import { useAuth } from '../store'

vi.mock('../api', async (orig) => {
  const real = await orig()
  const stub = { get: vi.fn((url) => Promise.resolve({ data: ['/users', '/departments'].includes(url) ? [] : { unread: 0, items: [], total: 0 } })), post: vi.fn(), patch: vi.fn() }
  return { ...real, api: stub }
})

const renderAt = (path) => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
const sign = (role) => useAuth.setState({ user: { id: 1, full_name: 'Test User', role }, access: 'a', refresh: 'r' })

describe('routing and role guards', () => {
  beforeEach(() => useAuth.setState({ user: null, access: null, refresh: null }))

  it('sends signed-out visitors to the login page', () => {
    renderAt('/complaints')
    expect(screen.getByRole('form', { name: /sign in/i })).toBeInTheDocument()
  })
  it('shows reporters the report form and their own menu only', async () => {
    sign('faculty')
    renderAt('/new')
    expect(await screen.findByRole('form', { name: /new complaint/i })).toBeInTheDocument()
    expect(screen.queryByText('Users')).not.toBeInTheDocument()
    expect(screen.getAllByText('Report a problem').length).toBeGreaterThan(0)
  })
  it('keeps reporters out of admin pages', async () => {
    sign('faculty')
    renderAt('/admin')
    await waitFor(() => expect(screen.getByRole('heading', { name: /my complaints/i })).toBeInTheDocument())
  })
  it('gives workers their queue and no report form', async () => {
    sign('maintenance')
    renderAt('/new')
    expect(await screen.findByRole('heading', { name: /my work/i })).toBeInTheDocument()
    expect(screen.getByText('Open jobs')).toBeInTheDocument()
  })
  it('gives admins the full menu', async () => {
    sign('admin')
    renderAt('/users')
    expect(await screen.findByRole('heading', { name: 'Users' })).toBeInTheDocument()
    for (const label of ['Dashboard', 'AI review', 'All complaints']) expect(screen.getByText(label)).toBeInTheDocument()
  })
})

describe('errorMessage', () => {
  it('reads the standard error body, including field details', () => {
    const e = { response: { data: { error: { code: 'validation_error', message: 'The request is not valid.', details: [{ field: 'block', message: 'required' }] } } } }
    expect(errorMessage(e)).toBe('The request is not valid. block: required')
  })
  it('explains network failures', () => {
    expect(errorMessage({ code: 'ERR_NETWORK' })).toMatch(/cannot reach the server/i)
  })
})
