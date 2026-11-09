// @vitest-environment jsdom
// Описание и доступ к викторине в редакторе (Must из docs/PLAN.md).
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'

import { Editor } from '../pages/Editor'
import { api } from './api'
import { clearDrafts } from './draft'
import type { Quiz } from './types'
import { blankQuestion } from './validate'

afterEach(() => { cleanup(); vi.restoreAllMocks(); clearDrafts() })

const quiz: Quiz = {
  id: 2, title: 'Космос', description: 'Для 5 класса', is_public: false, updated_at: 'v1',
  questions: [{ ...blankQuestion(), text: 'Вопрос', options: [
    { text: 'Да', is_correct: true }, { text: 'Нет', is_correct: false },
  ] }],
}

it('описание и доступ показываются, правятся и сохраняются', async () => {
  vi.spyOn(api, 'getQuiz').mockResolvedValue(quiz)
  const update = vi.spyOn(api, 'updateQuiz').mockResolvedValue({ ...quiz, updated_at: 'v2' })
  const router = createMemoryRouter([{ path: '/quizzes/:id/edit', element: <Editor /> }],
    { initialEntries: ['/quizzes/2/edit'] })
  render(<RouterProvider router={router} />)
  const description = await screen.findByLabelText('Описание')
  expect((description as HTMLTextAreaElement).value).toBe('Для 5 класса')
  expect(screen.getByText(/только у вас/)).toBeTruthy()
  fireEvent.change(description, { target: { value: 'Повторение перед контрольной' } })
  fireEvent.click(screen.getByRole('checkbox', { name: /Открыть другим ведущим/ }))
  expect(screen.getByText('Есть несохранённые изменения')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
  await waitFor(() => expect(update).toHaveBeenCalled())
  expect(update.mock.calls[0][1]).toMatchObject({ description: 'Повторение перед контрольной', is_public: true })
})
