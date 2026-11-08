// @vitest-environment jsdom
// Мелкие находки аудита готовности от 5 ноября: R07, R09, R11, R20.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, RouterProvider, createMemoryRouter } from 'react-router-dom'

import { Dashboard } from '../pages/Dashboard'
import { Editor } from '../pages/Editor'
import { Join } from '../pages/Join'
import { ApiError, api } from './api'
import { clearDrafts } from './draft'
import type { Quiz } from './types'
import { blankQuestion, questionProblems } from './validate'

vi.mock('./auth', () => ({
  useAuth: () => ({ user: { id: 1, email: 'u@example.com', username: 'Учитель' }, logout: () => {} }),
  useCurrentUser: () => ({ id: 1, email: 'u@example.com', username: 'Учитель' }),
}))

afterEach(() => { cleanup(); vi.restoreAllMocks(); clearDrafts() })

const quiz: Quiz = {
  id: 2, title: 'Существующая', description: '', is_public: false, updated_at: '2026-11-07T10:00:00.000001',
  questions: [{ ...blankQuestion(), text: 'Исходный вопрос', options: [
    { text: 'Да', is_correct: true }, { text: 'Нет', is_correct: false },
  ] }],
}

describe('R07: правки из другой вкладки', () => {
  it('конфликт версии не затирает чужие правки, можно сохранить поверх явно', async () => {
    vi.spyOn(api, 'getQuiz').mockResolvedValue(quiz)
    const update = vi.spyOn(api, 'updateQuiz')
      .mockRejectedValueOnce(new ApiError(409, 'Викторину уже изменили в другой вкладке'))
      .mockResolvedValueOnce({ ...quiz, updated_at: '2026-11-07T10:05:00.000001' })
    const router = createMemoryRouter([{ path: '/quizzes/:id/edit', element: <Editor /> }],
      { initialEntries: ['/quizzes/2/edit'] })
    render(<RouterProvider router={router} />)
    fireEvent.change(await screen.findByDisplayValue('Исходный вопрос'), { target: { value: 'Моя правка' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await screen.findByText(/уже изменили в другой вкладке/)
    expect(update.mock.calls[0][1].base_updated_at).toBe(quiz.updated_at)
    expect(screen.getByText('Есть несохранённые изменения')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить мои правки поверх' }))
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
    expect(update.mock.calls[1][1].base_updated_at).toBeNull()
    await screen.findByText('Сохранено')
  })
})

describe('R11: одинаковые варианты', () => {
  it('редактор не даёт сохранить повторяющиеся варианты и элементы', () => {
    const single = { ...blankQuestion('single'), text: '?', options: [
      { text: 'Юпитер', is_correct: true }, { text: '  юпитер ', is_correct: false },
    ] }
    expect(questionProblems(single)).toContain('Варианты ответа не должны повторяться')
    const order = { ...blankQuestion('order'), text: '?', options: [
      { text: 'А', is_correct: false }, { text: 'Б', is_correct: false }, { text: 'а', is_correct: false },
    ] }
    expect(questionProblems(order)).toContain('Элементы не должны повторяться — иначе порядок не определить')
  })
})

describe('R09: устаревший ответ по PIN', () => {
  it('ответ по старому коду не открывает комнату, если код уже поменяли', async () => {
    let resolveOld!: (v: { pin: string; title: string; status: string; player_count: number }) => void
    vi.spyOn(api, 'sessionByPin').mockImplementation(() => new Promise((r) => { resolveOld = r }))
    render(<MemoryRouter initialEntries={['/join?pin=111111']}><Join /></MemoryRouter>)
    fireEvent.change(screen.getByLabelText('Код комнаты, 6 цифр'), { target: { value: '22222' } })
    await act(async () => { resolveOld({ pin: '111111', title: 'Чужая комната', status: 'lobby', player_count: 3 }) })
    expect(screen.queryByText(/Чужая комната/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Дальше' })).toBeTruthy()
  })
})

describe('R20: частичная недоступность главной', () => {
  it('сбой истории не прячет список викторин', async () => {
    vi.spyOn(api, 'listQuizzes').mockResolvedValue([
      { id: 2, title: 'Космос', question_count: 3, updated_at: '2026-11-07T10:00:00' },
    ])
    vi.spyOn(api, 'history').mockRejectedValue(new Error('Сервер недоступен'))
    render(<MemoryRouter><Dashboard /></MemoryRouter>)
    expect(await screen.findByText('Космос')).toBeTruthy()
    expect(await screen.findByText(/Не удалось загрузить историю игр/)).toBeTruthy()
    expect(screen.queryByText('Загружаем…')).toBeNull()
  })
})
