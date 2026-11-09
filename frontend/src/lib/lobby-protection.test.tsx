// @vitest-environment jsdom
// Защита лобби (R01): кнопка «Закрыть вход» у ведущего и отказ на странице входа.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { Host } from '../pages/Host'
import { Join } from '../pages/Join'
import { api, setToken } from './api'

class FakeSocket {
  static OPEN = 1
  static last: FakeSocket
  readyState = 1
  onopen: null | (() => void) = null
  onclose = null
  onmessage: null | ((ev: { data: string }) => void) = null
  send = vi.fn()
  close = vi.fn()
  constructor() { FakeSocket.last = this }
  push(msg: Record<string, unknown>) { this.onmessage!({ data: JSON.stringify(msg) }) }
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); setToken(null) })

it('ведущий закрывает и открывает вход', () => {
  vi.stubGlobal('WebSocket', FakeSocket)
  setToken('host-token')
  render(
    <MemoryRouter initialEntries={['/host/482913']}>
      <Routes><Route path="/host/:pin" element={<Host />} /></Routes>
    </MemoryRouter>,
  )
  const ws = FakeSocket.last
  act(() => {
    ws.onopen!()
    ws.push({ type: 'state:snapshot', state: 'lobby', pin: '482913', title: 'Игра', serverNow: Date.now(),
      playerCount: 0, questionCount: 3, players: [], locked: false })
  })
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть вход' }))
  expect(JSON.parse(ws.send.mock.calls.at(-1)![0] as string)).toEqual({ type: 'host:lock' })
  act(() => { ws.push({ type: 'lobby:update', players: [], locked: true }) })
  const reopen = screen.getByRole('button', { name: 'Вход закрыт · открыть' })
  expect(reopen.getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(reopen)
  expect(JSON.parse(ws.send.mock.calls.at(-1)![0] as string)).toEqual({ type: 'host:unlock' })
})

it('в закрытую комнату новичок не попадает к вводу имени', async () => {
  vi.spyOn(api, 'sessionByPin').mockResolvedValue({
    pin: '482913', title: 'Игра', status: 'lobby', player_count: 5, accepting: false,
  })
  render(<MemoryRouter initialEntries={['/join?pin=482913']}><Join /></MemoryRouter>)
  expect(await screen.findByText('Ведущий закрыл вход в эту комнату')).toBeTruthy()
  expect(screen.queryByLabelText('Имя в игре')).toBeNull()
})
