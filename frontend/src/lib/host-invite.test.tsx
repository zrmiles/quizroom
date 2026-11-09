// @vitest-environment jsdom
// Приглашение в игру: QR-код со ссылкой на комнату (user story 5 в docs/PLAN.md).
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { Host } from '../pages/Host'
import { setToken } from './api'

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
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setToken(null) })

it('в лобби есть QR-код со ссылкой на эту комнату', () => {
  vi.stubGlobal('WebSocket', FakeSocket)
  setToken('host-token')
  render(
    <MemoryRouter initialEntries={['/host/482913']}>
      <Routes><Route path="/host/:pin" element={<Host />} /></Routes>
    </MemoryRouter>,
  )
  act(() => {
    FakeSocket.last.onopen!()
    FakeSocket.last.onmessage!({ data: JSON.stringify({
      type: 'state:snapshot', state: 'lobby', pin: '482913', title: 'Игра', serverNow: Date.now(),
      playerCount: 0, questionCount: 3, players: [],
    }) })
  })
  const qr = screen.getByRole('img', { name: 'QR-код для входа в комнату 482 913' })
  expect(qr.querySelector('path')?.getAttribute('d')).toMatch(/^M\d+ \d+h1v1h-1z/)
  // В строке с подписью код не должен сжиматься — иначе камера его не прочтёт.
  expect(qr.style.flexShrink).toBe('0')
})
