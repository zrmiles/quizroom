// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, RouterProvider, Routes, createMemoryRouter } from 'react-router-dom'

import { Editor } from '../pages/Editor'
import { Play, QuestionView } from '../pages/Play'
import { ApiError, api, getToken, setToken } from './api'
import { AuthProvider, RequireAuth } from './auth'
import { safeNext } from './navigation'
import { load, playerKey, remove, save } from './storage'
import type { PublicQuestion, Quiz } from './types'
import type { GameMessage } from './useGameSocket'
import { blankQuestion } from './validate'

const socket = vi.hoisted(() => ({ send: vi.fn(), onMessage: null as null | ((m: GameMessage) => void) }))
vi.mock('./useGameSocket', () => ({
  useGameSocket: (_pin: string, _role: string, _token: string, onMessage: (m: GameMessage) => void) => {
    socket.onMessage = onMessage
    return { status: 'open', deniedReason: null, send: socket.send, offsetRef: { current: 0 } }
  },
}))

beforeEach(() => {
  setToken(null)
  socket.send.mockReset().mockReturnValue(true)
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('сохранение активного входа', () => {
  it('работает в текущей вкладке при заблокированном хранилище и корректно выходит', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('blocked') })
    setToken('memory-token')
    save(playerKey('blocked'), { token: 'ticket', playerId: 1, nickname: 'Аня' })
    expect(getToken()).toBe('memory-token')
    expect(load(playerKey('blocked'))).toEqual({ token: 'ticket', playerId: 1, nickname: 'Аня' })
    setToken(null)
    remove(playerKey('blocked'))
    expect(getToken()).toBeNull()
    expect(load(playerKey('blocked'))).toBeNull()
  })

  it('сохраняет токен при сетевом сбое и позволяет повторить восстановление', async () => {
    setToken('valid-token')
    vi.spyOn(api, 'me').mockRejectedValueOnce(new ApiError(0, 'Нет связи')).mockResolvedValueOnce({
      id: 1, email: 'teacher@example.com', username: 'Учитель',
    })
    render(<MemoryRouter><AuthProvider><RequireAuth><p>Защищённая страница</p></RequireAuth></AuthProvider></MemoryRouter>)
    await screen.findByText('Нет связи')
    expect(getToken()).toBe('valid-token')
    fireEvent.click(screen.getByRole('button', { name: 'Попробовать снова' }))
    await screen.findByText('Защищённая страница')
  })

  it('очищает токен при подтверждённом 401', async () => {
    setToken('expired')
    vi.spyOn(api, 'me').mockRejectedValue(new ApiError(401, 'Сессия истекла'))
    render(<MemoryRouter><AuthProvider><p>Auth</p></AuthProvider></MemoryRouter>)
    await waitFor(() => expect(getToken()).toBeNull())
  })
})

describe('безопасная цель входа', () => {
  it.each(['//evil.invalid', '/\\evil.invalid', 'https://evil.invalid', 'javascript:alert(1)',
    '/a/..//evil.invalid', '/\nevil.invalid'])('отклоняет %s', (value) => {
    expect(safeNext(value, 'https://quiz.invalid')).toBe('/quizzes')
  })
  it('сохраняет внутренний путь с query и hash', () => {
    expect(safeNext('/quizzes/2/edit?view=all#q1', 'https://quiz.invalid')).toBe('/quizzes/2/edit?view=all#q1')
  })
})

const quiz: Quiz = {
  id: 2, title: 'Существующая викторина', description: 'Описание сохраняется', is_public: true, updated_at: '',
  questions: [{ ...blankQuestion(), text: 'Исходный вопрос', options: [
    { text: 'Да', is_correct: true }, { text: 'Нет', is_correct: false },
  ] }],
}
function editorRouter(path = '/quizzes/2/edit') {
  const router = createMemoryRouter([
    { path: '/quizzes/:id/edit', element: <Editor /> },
    { path: '/quizzes/new', element: <Editor /> },
    { path: '/quizzes', element: <p>Список викторин</p> },
  ], { initialEntries: [path] })
  render(<RouterProvider router={router} />)
  return router
}

describe('сохранение редактора', () => {
  it('после первого сохранения переходит к созданной викторине без потери полей и лишнего предупреждения', async () => {
    const create = vi.spyOn(api, 'createQuiz').mockResolvedValue(quiz)
    const get = vi.spyOn(api, 'getQuiz').mockResolvedValue(quiz)
    const router = editorRouter('/quizzes/new')
    fireEvent.change(screen.getByLabelText('Название викторины'), { target: { value: 'Моя новая викторина' } })
    fireEvent.change(screen.getByLabelText('Вопрос 1'), { target: { value: 'Новый вопрос' } })
    for (const letter of ['А', 'Б', 'В', 'Г']) {
      fireEvent.change(screen.getByLabelText(`Вариант ${letter}`), { target: { value: `Ответ ${letter}` } })
    }
    fireEvent.click(screen.getByRole('button', { name: 'Верный ответ: вариант А' }))
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/quizzes/2/edit'))
    expect(create).toHaveBeenCalledTimes(1)
    expect(get).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect((screen.getByLabelText('Вопрос 1') as HTMLTextAreaElement).value).toBe('Новый вопрос')
  })

  it('сохраняет метаданные и не помечает новые правки сохранёнными при старом ответе API', async () => {
    vi.spyOn(api, 'getQuiz').mockResolvedValue(quiz)
    let resolve!: (q: Quiz) => void
    const update = vi.spyOn(api, 'updateQuiz').mockReturnValue(new Promise<Quiz>((r) => { resolve = r }))
    editorRouter()
    await screen.findByDisplayValue(quiz.title)
    fireEvent.change(screen.getByLabelText('Вопрос 1'), { target: { value: 'Версия отправки' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(update).toHaveBeenCalledWith(2, expect.objectContaining({ description: quiz.description, is_public: true }))
    fireEvent.change(screen.getByLabelText('Вопрос 1'), { target: { value: 'Новая несохранённая версия' } })
    await act(async () => { resolve(quiz) })
    await screen.findByText('Есть несохранённые изменения')
    expect(screen.queryByText('Сохранено')).toBeNull()
    expect((screen.getByLabelText('Вопрос 1') as HTMLTextAreaElement).value).toBe('Новая несохранённая версия')
  })

  it('блокирует внутренний переход и позволяет остаться либо явно отказаться от правок', async () => {
    vi.spyOn(api, 'getQuiz').mockResolvedValue(quiz)
    editorRouter()
    await screen.findByDisplayValue(quiz.title)
    fireEvent.change(screen.getByLabelText('Вопрос 1'), { target: { value: 'Не терять' } })
    fireEvent.click(screen.getByRole('link', { name: '← Мои викторины' }))
    await screen.findByRole('alertdialog')
    fireEvent.click(screen.getByRole('button', { name: 'Остаться' }))
    expect((screen.getByLabelText('Вопрос 1') as HTMLTextAreaElement).value).toBe('Не терять')
    fireEvent.click(screen.getByRole('link', { name: '← Мои викторины' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Уйти без сохранения' }))
    await screen.findByText('Список викторин')
  })
})

const question: PublicQuestion = {
  index: 0, total: 1, type: 'number', text: 'Числовой вопрос', time_limit: 60,
  min: 0.1, max: 0.2, options: [],
}
describe('числовой ввод и подтверждение ответа', () => {
  it('начинает внутри дробной шкалы и отправляет точное значение', () => {
    const onAnswer = vi.fn()
    render(<QuestionView q={question} endsAt={Date.now() + 60_000} offsetRef={{ current: 0 }}
      answered={false} myChoice={null} onAnswer={onAnswer} error={null} />)
    const input = screen.getByLabelText('Введите точное значение') as HTMLInputElement
    expect(Number(input.value)).toBeCloseTo(0.15)
    fireEvent.change(input, { target: { value: '0.15' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ответить: 0,15' }))
    expect(onAnswer).toHaveBeenCalledWith({ number: 0.15 })
    fireEvent.change(input, { target: { value: '0' } })
    expect((screen.getByRole('button', { name: 'Ответить' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('не ограничивает точность шага ползунка при прямом вводе', () => {
    const onAnswer = vi.fn()
    render(<QuestionView q={{ ...question, min: 0, max: 100 }} endsAt={Date.now() + 60_000}
      offsetRef={{ current: 0 }} answered={false} myChoice={null} onAnswer={onAnswer} error={null} />)
    fireEvent.change(screen.getByLabelText('Введите точное значение'), { target: { value: '3.14' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ответить: 3,14' }))
    expect(onAnswer).toHaveBeenCalledWith({ number: 3.14 })
  })

  it('отправляет один выбор до ACK и использует подтверждённое сервером значение', async () => {
    save(playerKey('123456'), { token: 'ticket', playerId: 1, nickname: 'Аня' })
    render(<MemoryRouter initialEntries={['/play/123456']}><Routes>
      <Route path="/play/:pin" element={<Play />} />
    </Routes></MemoryRouter>)
    const q = { ...question, type: 'single', options: [{ id: 1, text: 'Первый' }, { id: 2, text: 'Второй' }] }
    await act(async () => { socket.onMessage!({ type: 'state:snapshot', state: 'question', question: q,
      endsAt: Date.now() + 60_000, playerCount: 1, you: null }) })
    const first = screen.getByRole('button', { name: /^А\s*Первый$/ })
    const second = screen.getByRole('button', { name: /^Б\s*Второй$/ })
    fireEvent.click(first)
    fireEvent.click(second)
    expect(socket.send).toHaveBeenCalledTimes(1)
    expect((second as HTMLButtonElement).disabled).toBe(true)
    await act(async () => { socket.onMessage!({ type: 'answer:ack', questionIndex: 0, value: { option_id: 1 } }) })
    await screen.findByText('Ответ принят · ждём остальных')
    expect(first.getAttribute('aria-pressed')).toBe('true')
    expect(second.getAttribute('aria-pressed')).toBe('false')
  })
})
