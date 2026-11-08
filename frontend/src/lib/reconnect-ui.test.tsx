// @vitest-environment jsdom
// R10 и R20 из аудита готовности от 5 ноября: состояние связи и принятого ответа после переподключения.
import { act, cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { Host } from '../pages/Host'
import { QuestionView } from '../pages/Play'
import { setToken } from './api'
import type { PublicQuestion } from './types'
import { useGameSocket } from './useGameSocket'

class FakeSocket {
  static OPEN = 1
  static all: FakeSocket[] = []
  readyState = 1
  onopen: null | (() => void) = null
  onclose: null | ((ev: { code: number }) => void) = null
  onmessage: null | ((ev: { data: string }) => void) = null
  send = vi.fn()
  close = vi.fn()
  constructor() { FakeSocket.all.push(this) }
  push(msg: Record<string, unknown>) { this.onmessage!({ data: JSON.stringify(msg) }) }
}

beforeEach(() => {
  FakeSocket.all = []
  vi.stubGlobal('WebSocket', FakeSocket)
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); setToken(null) })

const question = (over: Partial<PublicQuestion>): PublicQuestion => ({
  index: 0, total: 3, type: 'single', text: 'Вопрос', time_limit: 20, options: [], ...over,
})

describe('R10: принятый ответ после переподключения', () => {
  it('«угадай число» показывает принятое значение, а не середину шкалы', () => {
    render(<QuestionView q={question({ type: 'number', min: 0, max: 100 })} endsAt={Date.now() + 10_000}
      offsetRef={{ current: 0 }} answered myChoice={{ number: 18 }} onAnswer={() => {}} error={null} />)
    expect((screen.getByLabelText('Введите точное значение') as HTMLInputElement).value).toBe('18')
    expect(screen.queryByText('50')).toBeNull()
  })

  it('«по порядку» показывает принятый порядок', () => {
    const options = [{ id: 11, text: 'Первый' }, { id: 22, text: 'Второй' }, { id: 33, text: 'Третий' }]
    render(<QuestionView q={question({ type: 'order', options })} endsAt={Date.now() + 10_000}
      offsetRef={{ current: 0 }} answered myChoice={{ order: [33, 11, 22] }} onAnswer={() => {}} error={null} />)
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items[0]).toContain('Третий')
    expect(items[1]).toContain('Первый')
  })
})

describe('R10: связь готова только после ответа сервера', () => {
  it('до снимка состояния команды не отправляются', () => {
    const { result } = renderHook(() => useGameSocket('123456', 'player', 'token', () => {}))
    const ws = FakeSocket.all[0]
    act(() => { ws.onopen!() })
    expect(result.current.status).toBe('connecting')
    expect(result.current.send({ type: 'player:wave' })).toBe(false)
    act(() => { ws.push({ type: 'state:snapshot', state: 'lobby', serverNow: Date.now() }) })
    expect(result.current.status).toBe('open')
    expect(result.current.send({ type: 'player:wave' })).toBe(true)
  })
})

describe('R10/R20: кнопки ведущего', () => {
  function openHost() {
    setToken('host-token')
    render(
      <MemoryRouter initialEntries={['/host/123456']}>
        <Routes><Route path="/host/:pin" element={<Host />} /></Routes>
      </MemoryRouter>,
    )
    const ws = FakeSocket.all[0]
    act(() => {
      ws.onopen!()
      ws.push({
        type: 'state:snapshot', state: 'question', pin: '123456', title: 'Игра', serverNow: Date.now(),
        playerCount: 2, questionCount: 3, players: [], answered: 1, endsAt: Date.now() + 20_000,
        question: question({ index: 1, options: [{ id: 1, text: 'Да' }, { id: 2, text: 'Нет' }] }),
      })
    })
    return ws
  }

  it('«Закрыть вопрос» передаёт номер вопроса', () => {
    const ws = openHost()
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть вопрос' }))
    const sent = ws.send.mock.calls.map(([raw]) => JSON.parse(raw as string))
    expect(sent).toContainEqual({ type: 'host:skip', questionIndex: 1 })
  })

  it('при переподключении кнопки выключены', () => {
    const ws = openHost()
    act(() => { ws.onclose!({ code: 1006 }) })
    expect(screen.getByText('Переподключаемся…')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Закрыть вопрос' })).toHaveProperty('disabled', true)
  })
})
