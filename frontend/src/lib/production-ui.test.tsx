// @vitest-environment jsdom
// Доработки к выкладке: модерация во время игры, аккаунт, история по страницам, устойчивость интерфейса.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { ErrorBoundary } from '../components/ErrorBoundary'
import { Account } from '../pages/Account'
import { Dashboard } from '../pages/Dashboard'
import { Host } from '../pages/Host'
import { Play } from '../pages/Play'
import { api, setToken } from './api'
import { formatDate } from './format'
import { playerKey, remove, save } from './storage'
import type { SessionHistoryItem } from './types'

const auth = vi.hoisted(() => ({
  changePassword: vi.fn(),
  logoutEverywhere: vi.fn(),
}))
vi.mock('./auth', () => ({
  useAuth: () => ({
    user: { id: 1, email: 'u@example.com', username: 'Учитель' },
    logout: () => {},
    changePassword: auth.changePassword,
    logoutEverywhere: auth.logoutEverywhere,
  }),
}))
vi.mock('../components/TopBar', () => ({ TopBar: () => null }))

class FakeSocket {
  static OPEN = 1
  static last: FakeSocket
  readyState = 1
  onopen: null | (() => void) = null
  onclose: null | ((ev: { code: number }) => void) = null
  onmessage: null | ((ev: { data: string }) => void) = null
  send = vi.fn()
  close = vi.fn()
  constructor() { FakeSocket.last = this }
  deliver(msg: object) { this.onmessage!({ data: JSON.stringify(msg) }) }
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setToken(null); remove(playerKey('111111')) })

const AV = { shape: 'round' as const, color: '#FF7A59', eyes: 2 }

describe('ведущий во время игры', () => {
  it('может удалить игрока из списка участников', () => {
    vi.stubGlobal('WebSocket', FakeSocket)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    setToken('host-token')
    render(
      <MemoryRouter initialEntries={['/host/111111']}>
        <Routes><Route path="/host/:pin" element={<Host />} /></Routes>
      </MemoryRouter>,
    )
    act(() => {
      FakeSocket.last.onopen!()
      FakeSocket.last.deliver({
        type: 'state:snapshot', state: 'question', pin: '111111', title: 'Игра', serverNow: Date.now(),
        playerCount: 2, questionCount: 3, endsAt: Date.now() + 20000, answered: 0,
        question: { index: 0, total: 3, type: 'single', text: 'Вопрос', time_limit: 20, options: [] },
        players: [
          { id: 1, nickname: 'Аня', avatar: AV, connected: true, score: 0 },
          { id: 2, nickname: 'Тролль', avatar: AV, connected: true, score: 0 },
        ],
      })
    })
    fireEvent.click(screen.getByRole('button', { name: 'Участники · 2' }))
    fireEvent.click(screen.getByRole('button', { name: 'Удалить игрока Тролль' }))
    const sent = FakeSocket.last.send.mock.calls.map((c) => JSON.parse(c[0] as string))
    expect(sent).toContainEqual({ type: 'host:kick', player_id: 2 })
  })

  it('может закрыть лобби', () => {
    vi.stubGlobal('WebSocket', FakeSocket)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    setToken('host-token')
    render(
      <MemoryRouter initialEntries={['/host/111111']}>
        <Routes><Route path="/host/:pin" element={<Host />} /></Routes>
      </MemoryRouter>,
    )
    act(() => {
      FakeSocket.last.onopen!()
      FakeSocket.last.deliver({
        type: 'state:snapshot', state: 'lobby', pin: '111111', title: 'Игра', serverNow: Date.now(),
        playerCount: 0, questionCount: 3, players: [],
      })
    })
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть комнату' }))
    const sent = FakeSocket.last.send.mock.calls.map((c) => JSON.parse(c[0] as string))
    expect(sent).toContainEqual({ type: 'host:end' })
  })
})

it('игрок, открывший игру в другой вкладке, видит понятную причину', () => {
  vi.stubGlobal('WebSocket', FakeSocket)
  save(playerKey('111111'), { token: 't', playerId: 1, nickname: 'Аня' })
  render(
    <MemoryRouter initialEntries={['/play/111111']}>
      <Routes><Route path="/play/:pin" element={<Play />} /></Routes>
    </MemoryRouter>,
  )
  act(() => { FakeSocket.last.onopen!(); FakeSocket.last.onclose!({ code: 4409 }) })
  expect(screen.getByText('Игра открыта в другой вкладке или на другом устройстве')).toBeTruthy()
})

describe('аккаунт', () => {
  it('меняет пароль только при совпадении повтора', async () => {
    auth.changePassword.mockResolvedValue(undefined)
    render(<MemoryRouter><Account /></MemoryRouter>)
    fireEvent.change(screen.getByLabelText('Текущий пароль'), { target: { value: 'old-password' } })
    fireEvent.change(screen.getByLabelText('Новый пароль'), { target: { value: 'new-password-1' } })
    fireEvent.change(screen.getByLabelText('Новый пароль ещё раз'), { target: { value: 'new-password-2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сменить пароль' }))
    expect(await screen.findByText('Пароли не совпадают')).toBeTruthy()
    expect(auth.changePassword).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('Новый пароль ещё раз'), { target: { value: 'new-password-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сменить пароль' }))
    expect(await screen.findByText(/Пароль изменён/)).toBeTruthy()
    expect(auth.changePassword).toHaveBeenCalledWith('old-password', 'new-password-1')
  })
})

describe('история игр', () => {
  const item = (id: number): SessionHistoryItem => ({
    id, pin: '111111', title: `Игра ${id}`, status: 'finished', created_at: '2026-11-20T10:00:00Z',
    player_count: 1, question_count: 1, parent_session_id: null, has_report: true,
  })

  it('догружает следующую страницу', async () => {
    vi.spyOn(api, 'listQuizzes').mockResolvedValue([])
    const history = vi.spyOn(api, 'history').mockImplementation(async (before?: number) =>
      before ? [item(1)] : Array.from({ length: 50 }, (_, i) => item(100 - i)))
    render(<MemoryRouter><Dashboard /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: 'Показать ещё' }))
    await screen.findByText('Игра 1')
    expect(history).toHaveBeenLastCalledWith(51)
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Показать ещё' })).toBeNull())
  })
})

it('ошибка отрисовки показывает объяснение, а не белый экран', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  const Broken = () => { throw new Error('boom') }
  render(<ErrorBoundary><Broken /></ErrorBoundary>)
  expect(screen.getByRole('button', { name: 'Обновить страницу' })).toBeTruthy()
})

it('дата с отрицательным смещением пояса разбирается верно', () => {
  expect(formatDate('2026-11-20T10:00:00-05:00')).toBe(formatDate('2026-11-20T15:00:00Z'))
  expect(formatDate('2026-11-20T15:00:00')).toBe(formatDate('2026-11-20T15:00:00Z'))
})
