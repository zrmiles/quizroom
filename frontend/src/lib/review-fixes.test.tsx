// @vitest-environment jsdom
// Регрессии на дефекты B01, B02 и B06 из внешнего ревью (2 ноября).
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'

import { Editor } from '../pages/Editor'
import { ApiError, api } from './api'
import { clearDrafts } from './draft'
import type { Quiz } from './types'
import { reconnectDelay, useGameSocket } from './useGameSocket'
import { blankQuestion } from './validate'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); clearDrafts() })

const quiz: Quiz = {
  id: 2, title: 'Существующая', description: 'Описание', is_public: true, updated_at: '',
  questions: [{ ...blankQuestion(), text: 'Исходный вопрос', options: [
    { text: 'Да', is_correct: true }, { text: 'Нет', is_correct: false },
  ] }],
}

function setup() {
  const router = createMemoryRouter([
    { path: '/quizzes/:id/edit', element: <Editor /> },
    { path: '/quizzes', element: <p>Мои викторины</p> },
    { path: '/host/:pin', element: <p>Экран ведущего</p> },
  ], { initialEntries: ['/quizzes/2/edit'] })
  render(<RouterProvider router={router} />)
  return router
}

describe('B01: ошибка загрузки не даёт перезаписать викторину', () => {
  it('редактор не открывается, повтор загрузки возвращает исходные данные', async () => {
    const get = vi.spyOn(api, 'getQuiz').mockRejectedValueOnce(new ApiError(503, 'Сервер недоступен'))
    const update = vi.spyOn(api, 'updateQuiz').mockResolvedValue(quiz)
    setup()
    await screen.findByText('Сервер недоступен')
    expect(screen.queryByLabelText('Вопрос 1')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).toBeNull()

    get.mockResolvedValueOnce(quiz)
    fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }))
    await screen.findByDisplayValue('Исходный вопрос')
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    const [, payload] = update.mock.calls[0]
    expect(payload.questions[0].text).toBe('Исходный вопрос')
    expect(payload.description).toBe('Описание')
    expect(payload.is_public).toBe(true)
  })
})

describe('B02: правки во время создания комнаты не теряются', () => {
  it('во время запуска поля заблокированы', async () => {
    vi.spyOn(api, 'getQuiz').mockResolvedValue(quiz)
    let resolve!: (v: { id: number; pin: string }) => void
    vi.spyOn(api, 'createSession').mockReturnValue(new Promise((r) => { resolve = r }))
    const router = setup()
    await screen.findByDisplayValue('Исходный вопрос')
    fireEvent.click(screen.getByRole('button', { name: 'Запустить игру' }))
    // Поле внутри заблокированного fieldset: своё свойство disabled — false, но поле недоступно.
    await waitFor(() => expect(screen.getByLabelText('Вопрос 1').matches(':disabled')).toBe(true))
    expect((screen.getByLabelText('Название викторины') as HTMLInputElement).disabled).toBe(true)
    await act(async () => { resolve({ id: 7, pin: '555555' }) })
    await waitFor(() => expect(router.state.location.pathname).toBe('/host/555555'))
  })

  it('если правка всё же появилась — остаёмся в редакторе', async () => {
    vi.spyOn(api, 'getQuiz').mockResolvedValue(quiz)
    let resolve!: (v: { id: number; pin: string }) => void
    vi.spyOn(api, 'createSession').mockReturnValue(new Promise((r) => { resolve = r }))
    const router = setup()
    await screen.findByDisplayValue('Исходный вопрос')
    fireEvent.click(screen.getByRole('button', { name: 'Запустить игру' }))
    // Обходим блокировку поля напрямую — как если бы правка пришла иным путём.
    fireEvent.change(screen.getByLabelText('Вопрос 1'), { target: { value: 'Правка во время запуска' } })
    await act(async () => { resolve({ id: 7, pin: '555555' }) })
    expect(router.state.location.pathname).toBe('/quizzes/2/edit')
    await screen.findByText(/появились новые правки/)
  })
})

describe('B06: задержка переподключений', () => {
  it('растёт и ограничена 5 с, разброс до 30%', () => {
    expect([1, 2, 3, 4, 5].map((n) => reconnectDelay(n, () => 0))).toEqual([1000, 2000, 4000, 5000, 5000])
    expect(reconnectDelay(1, () => 1)).toBe(1300)
  })

  it('не сбрасывается, если соединение открывается и сразу закрывается', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const sockets: FakeSocket[] = []
    class FakeSocket {
      static OPEN = 1
      readyState = 1
      onopen: null | (() => void) = null
      onclose: null | ((ev: { code: number }) => void) = null
      onmessage = null
      send = vi.fn()
      close = vi.fn()
      constructor() { sockets.push(this) }
    }
    vi.stubGlobal('WebSocket', FakeSocket)
    renderHook(() => useGameSocket('123456', 'player', 'token', () => {}))
    const delays: number[] = []
    for (let i = 0; i < 4; i++) {
      await act(async () => { sockets[i].onopen!(); sockets[i].onclose!({ code: 1013 }) })
      let waited = 0
      while (sockets.length === i + 1 && waited < 10_000) {
        await act(async () => { vi.advanceTimersByTime(100) })
        waited += 100
      }
      delays.push(waited)
    }
    expect(delays).toEqual([1000, 2000, 4000, 5000])
  })
})
