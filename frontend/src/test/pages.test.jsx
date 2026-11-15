import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { api } from '../api'
import { useAuth } from '../store'

vi.mock('../imageTools', () => ({ shrinkImage: vi.fn((f) => Promise.resolve(f)) }))
vi.mock('../api', async (orig) => {
  const real = await orig()
  return { ...real, login: vi.fn(), logout: vi.fn(), api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }
})
import { login } from '../api'

const complaint = (o = {}) => ({
  id: 1, complaint_number: 'CN-00001', title: 'Fan broken', description: 'Fan not working', location: 'A, 1', category: 'electrical', priority: 'high',
  status: 'registered', reported_by: 10, assigned_to: null, safety_risk: false, needs_manual_review: false, escalation_level: 0,
  sla_hours: 24, sla_due_at: '2026-01-02T00:00:00', created_at: '2026-01-01T00:00:00', images: [], history: [], ...o,
})
const routes = (map) => api.get.mockImplementation((url) => {
  const keys = Object.keys(map).filter((k) => url === k || url.startsWith(k)).sort((a, b) => (b === url) - (a === url) || b.length - a.length)
  if (keys.length) { const v = map[keys[0]]; return Promise.resolve({ data: typeof v === 'function' ? v(url) : v }) }
  return Promise.resolve({ data: { unread: 0 } })
})
const sign = (role, id = 10) => useAuth.setState({ user: { id, full_name: 'Test User', role }, access: 'a', refresh: 'r' })
const at = (path) => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  useAuth.setState({ user: null, access: null, refresh: null })
})

describe('login', () => {
  it('signs in and lands on the role home', async () => {
    login.mockResolvedValue({ user: { id: 1, full_name: 'Adm', role: 'admin' }, access_token: 'a', refresh_token: 'r' })
    routes({ '/dashboard/admin': { total_complaints: 0, open_complaints: 0, by_priority: [], by_category: [], by_status: [] }, '/dashboard/emergencies': [], '/dashboard/ai-performance': {} })
    at('/login')
    await userEvent.type(screen.getByLabelText('Email'), 'admin@x.t')
    await userEvent.type(screen.getByLabelText('Password'), 'Pass1234')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(login).toHaveBeenCalledWith('admin@x.t', 'Pass1234')
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(useAuth.getState().access).toBe('a')
  })
  it('shows the server message for a bad password', async () => {
    login.mockRejectedValue({ response: { data: { error: { code: 'unauthorized', message: 'Invalid email or password.' } } } })
    at('/login')
    await userEvent.type(screen.getByLabelText('Email'), 'a@x.t')
    await userEvent.type(screen.getByLabelText('Password'), 'bad')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.')
  })
})

describe('reporter pages', () => {
  it('files a complaint and shows the AI result', async () => {
    sign('faculty'); routes({})
    api.post.mockResolvedValue({ data: complaint({ id: 5, complaint_number: 'CN-00005', status: 'assigned', sla_hours: 4, priority: 'critical' }) })
    at('/new')
    await userEvent.type(screen.getByPlaceholderText('Block A'), 'Block D')
    await userEvent.type(screen.getByPlaceholderText('2'), '3')
    await userEvent.type(screen.getByPlaceholderText(/Describe the problem/), 'Sparks from the switch board')
    await userEvent.click(screen.getByRole('button', { name: 'Submit complaint' }))
    expect(await screen.findByText('Complaint registered')).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/complaints', expect.objectContaining({ block: 'Block D', floor: '3', room_number: null }))
    expect(screen.getByText(/already been assigned automatically/)).toBeInTheDocument()
    expect(screen.getByText('CN-00005')).toBeInTheDocument()
  })
  it('shows validation errors from the API', async () => {
    sign('faculty'); routes({})
    api.post.mockRejectedValue({ response: { data: { error: { code: 'validation_error', message: 'The request is not valid.', details: [{ field: 'description', message: 'too vague' }] } } } })
    at('/new')
    await userEvent.type(screen.getByPlaceholderText('Block A'), 'B')
    await userEvent.type(screen.getByPlaceholderText('2'), '1')
    await userEvent.type(screen.getByPlaceholderText(/Describe the problem/), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Submit complaint' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('description: too vague')
  })
  it('lists complaints, filters them and opens details', async () => {
    sign('faculty')
    routes({ '/complaints': { items: [complaint()], total: 1, page: 1, page_size: 10 }, '/complaints/1': complaint({ history: [{ id: 1, old_status: null, new_status: 'registered', remarks: 'Complaint registered', created_at: '2026-01-01T00:00:00' }] }) })
    at('/complaints')
    expect(await screen.findByText('CN-00001')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'assigned')
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/complaints', { params: expect.objectContaining({ status: 'assigned' }) }))
    await userEvent.click(screen.getByText('CN-00001'))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Complaint registered')).toBeInTheDocument()
  })
  it('reporter can confirm a resolved complaint', async () => {
    sign('faculty', 10)
    routes({ '/complaints': { items: [complaint({ status: 'resolved' })], total: 1, page: 1, page_size: 10 }, '/complaints/1': complaint({ status: 'resolved' }) })
    api.post.mockResolvedValue({ data: {} })
    at('/complaints')
    await userEvent.click(await screen.findByText('CN-00001'))
    await userEvent.click(await screen.findByRole('button', { name: /Confirm fixed/ }))
    expect(api.post).toHaveBeenCalledWith('/complaints/1/sign-off', undefined)
  })
})

describe('worker pages', () => {
  it('shows my numbers and jobs', async () => {
    sign('maintenance', 20)
    routes({ '/complaints': { items: [complaint({ status: 'assigned', assigned_to: 20 })], total: 1 }, '/dashboard/maintenance/20': { assigned: 3, in_progress: 1, resolved_today: 2, tasks: [] } })
    at('/work')
    expect(await screen.findByText('CN-00001')).toBeInTheDocument()
    const stats = await screen.findByLabelText('My numbers')
    expect(within(stats).getByText('3')).toBeInTheDocument()
  })
  it('takes a job from the pool', async () => {
    sign('maintenance', 20)
    routes({ '/complaints/pool': [complaint()] })
    api.post.mockResolvedValue({ data: {} })
    at('/pool')
    await userEvent.click(await screen.findByRole('button', { name: 'Take this job' }))
    expect(api.post).toHaveBeenCalledWith('/complaints/1/claim')
  })
  it('a worker can start an assigned job and must write a note to resolve', async () => {
    sign('maintenance', 20)
    routes({ '/complaints': { items: [complaint({ status: 'in_progress', assigned_to: 20 })], total: 1 }, '/complaints/1': complaint({ status: 'in_progress', assigned_to: 20 }), '/dashboard/maintenance/20': { assigned: 1, in_progress: 1, resolved_today: 0 } })
    api.post.mockResolvedValue({ data: {} })
    at('/work')
    await userEvent.click(await screen.findByText('CN-00001'))
    const resolve = await screen.findByRole('button', { name: 'Mark resolved' })
    expect(resolve).toBeDisabled()
    await userEvent.type(screen.getByPlaceholderText(/What was done/), 'Replaced capacitor')
    await userEvent.click(resolve)
    expect(api.post).toHaveBeenCalledWith('/complaints/1/status', { status: 'resolved', note: 'Replaced capacitor' })
  })
})

describe('admin pages', () => {
  it('renders the dashboard numbers and emergency list', async () => {
    sign('admin', 1)
    routes({
      '/dashboard/admin': { total_complaints: 9, open_complaints: 4, critical_open: 2, overdue_complaints: 1, escalated_open: 0, unassigned_open: 1, pending_ai_reviews: 3, avg_resolution_hours: 5.5, by_priority: [{ priority: 'high', count: 2 }], by_category: [{ category: 'electrical', count: 2 }], by_status: [{ status: 'registered', count: 1 }] },
      '/dashboard/emergencies': [{ complaint_id: 7, title: 'Gas leak', location: 'Lab', priority: 'critical', status: 'assigned', hours_to_deadline: -2.5, is_overdue: true, escalation_level: 1, safety_risk: true }],
      '/dashboard/ai-performance': { total_predictions: 20, flagged_for_review: 3, agreement_rate_pct: 80, overridden: 1, avg_priority_confidence: 0.82 },
    })
    at('/admin')
    expect(await screen.findByText('Gas leak')).toBeInTheDocument()
    expect(screen.getByText('2.5h overdue')).toBeInTheDocument()
    expect(screen.getByText('AI reviews waiting').nextSibling).toHaveTextContent('3')
    expect(screen.getByText('80%')).toBeInTheDocument()
  })
  it('AI review: confirm and override', async () => {
    sign('admin', 1)
    routes({ '/ai/reviews': [{ prediction_id: 4, complaint_id: 9, title: 'Odd text', input_text: 'asdf', predicted_category: 'general', predicted_priority: 'low', category_confidence: 0.4, priority_confidence: 0.5, reasons: ['no strong signal'], source: 'ml' }] })
    api.post.mockResolvedValue({ data: {} })
    at('/reviews')
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm AI result' }))
    expect(api.post).toHaveBeenCalledWith('/ai/predictions/4/confirm', { notes: '' })
    await userEvent.selectOptions(await screen.findByLabelText('Category'), 'networking')
    await userEvent.click(screen.getByRole('button', { name: 'Override with my choice' }))
    expect(api.post).toHaveBeenCalledWith('/ai/predictions/4/override', { category: 'networking', priority: 'low', notes: '' })
  })
  it('routing editor saves a department and a switch', async () => {
    sign('admin', 1)
    routes({ '/routing-rules': [{ id: 1, category: 'electrical', department_id: 2, is_active: true }], '/departments': [{ id: 2, name: 'EEE' }, { id: 3, name: 'Civil' }] })
    api.put.mockResolvedValue({ data: {} })
    at('/routing')
    const select = await screen.findByLabelText('Department for electrical')
    await userEvent.selectOptions(select, '3')
    expect(api.put).toHaveBeenCalledWith('/routing-rules/electrical', { department_id: 3, is_active: true })
    await userEvent.click(screen.getByLabelText('Active electrical'))
    expect(api.put).toHaveBeenLastCalledWith('/routing-rules/electrical', { department_id: 2, is_active: false })
  })
  it('users: lists accounts and disables one', async () => {
    sign('admin', 1)
    routes({ '/users': [{ id: 1, full_name: 'Admin', email: 'a@x.t', role: 'admin', department_id: null, is_active: true }, { id: 2, full_name: 'Ravi', email: 'r@x.t', role: 'maintenance', department_id: 2, is_active: true }], '/departments': [{ id: 2, name: 'EEE' }] })
    api.patch.mockResolvedValue({ data: {} })
    at('/users')
    await screen.findByText('Ravi')
    await userEvent.click(screen.getByRole('button', { name: 'Disable' }))
    expect(api.patch).toHaveBeenCalledWith('/users/2', { is_active: false })
  })
})

describe('notifications', () => {
  it('shows notifications and saves preferences', async () => {
    sign('faculty')
    routes({ '/notifications': [{ id: 1, title: 'Assigned', message: 'To Ravi', is_read: false, created_at: '2026-01-01T00:00:00' }], '/auth/me/notification-preferences': { email: true, push: true, in_app: true, fcm_token: null } })
    api.put.mockResolvedValue({ data: { email: false, push: true, in_app: true } })
    at('/notifications')
    expect(await screen.findByText('Assigned')).toBeInTheDocument()
    await userEvent.click(await screen.findByLabelText('E-mail'))
    expect(api.put).toHaveBeenCalledWith('/auth/me/notification-preferences', { email: false, push: true, in_app: true, fcm_token: null })
  })
})

describe('history', () => {
  it('worker sees finished jobs with time taken and totals', async () => {
    sign('maintenance', 20)
    const done = complaint({ status: 'resolved', assigned_to: 20, created_at: '2026-01-01T00:00:00', resolved_at: '2026-01-01T03:00:00', sla_due_at: '2026-01-02T00:00:00' })
    routes({ '/complaints': (u) => ({ items: [done], total: 1 }) })
    api.get.mockImplementation((url, cfg) => Promise.resolve({ data: cfg?.params?.status === 'resolved' ? { items: [done], total: 1 } : cfg?.params?.status === 'closed' ? { items: [], total: 0 } : { unread: 0 } }))
    at('/history')
    expect(await screen.findByRole('heading', { name: 'My work history' })).toBeInTheDocument()
    expect(await screen.findByText('CN-00001')).toBeInTheDocument()
    expect(screen.getAllByText('3.0 h').length).toBeGreaterThan(0)
    expect(within(screen.getByLabelText('History numbers')).getByText('100%')).toBeInTheDocument()
  })
  it('shows an empty message when nothing is finished', async () => {
    sign('faculty')
    api.get.mockImplementation((url, cfg) => Promise.resolve({ data: cfg?.params?.status ? { items: [], total: 0 } : { unread: 0 } }))
    at('/history')
    expect(await screen.findByText(/Nothing finished yet/)).toBeInTheDocument()
  })
})