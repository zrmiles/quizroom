// @vitest-environment jsdom
// R26 из аудита готовности от 5 ноября: истечение входа не должно уничтожать несохранённые правки.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Outlet, RouterProvider, createMemoryRouter } from 'react-router-dom'

import { Editor } from '../pages/Editor'
import { api, getToken, setToken } from './api'
import { AuthProvider, RequireAuth } from './auth'
import { clearDrafts, draftKey, loadDraft, saveDraft } from './draft'
import type { Quiz } from './types'
import { blankQuestion } from './validate'

const quiz: Quiz = {
  id: 2, title: 'Существующая', description: '', is_public: false, updated_at: '',
  questions: [{ ...blankQuestion(), text: 'Исходный вопрос', options: [
    { text: 'Да', is_correct: true }, { text: 'Нет', is_correct: false },
  ] }],
}

beforeEach(() => {
  clearDrafts()
  setToken(null)
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

function openEditor(userId: number) {
  setToken(`token-${userId}`)
  vi.spyOn(api, 'me').mockResolvedValue({ id: userId, email: `u${userId}@example.com`, username: 'Учитель' })
  vi.spyOn(api, 'getQuiz').mockResolvedValue(quiz)
  const router = createMemoryRouter([
    {
      element: <AuthProvider><Outlet /></AuthProvider>,
      children: [
        { path: '/quizzes/:id/edit', element: <RequireAuth><Editor /></RequireAuth> },
        { path: '/login', element: <p>Страница входа</p> },
      ],
    },
  ], { initialEntries: ['/quizzes/2/edit'] })
  render(<RouterProvider router={router} />)
  return router
}

async function editAndHitExpiredSave() {
  openEditor(1)
  fireEvent.change(await screen.findByDisplayValue('Исходный вопрос'), { target: { value: 'Новая правка' } })
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Войдите снова' }), {
    status: 401, headers: { 'Content-Type': 'application/json' },
  })))
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
  await screen.findByText('Страница входа')
  expect(getToken()).toBeNull()
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
}

describe('R26: черновик при истечении входа', () => {
  it('после повторного входа тем же аккаунтом правки восстанавливаются', async () => {
    await editAndHitExpiredSave()
    openEditor(1)
    expect(await screen.findByDisplayValue('Новая правка')).toBeTruthy()
    expect(screen.getByText(/Восстановили правки/)).toBeTruthy()
    expect(screen.getByText('Есть несохранённые изменения')).toBeTruthy()
  })

  it('другой аккаунт черновик не видит', async () => {
    await editAndHitExpiredSave()
    openEditor(7)
    expect(await screen.findByDisplayValue('Исходный вопрос')).toBeTruthy()
    expect(screen.queryByText(/Восстановили правки/)).toBeNull()
  })

  it('можно вернуть сохранённую версию', async () => {
    await editAndHitExpiredSave()
    openEditor(1)
    await screen.findByDisplayValue('Новая правка')
    fireEvent.click(screen.getByRole('button', { name: 'Вернуть сохранённую версию' }))
    expect(await screen.findByDisplayValue('Исходный вопрос')).toBeTruthy()
    expect(loadDraft(draftKey(1, 2))).toBeNull()
  })

  it('успешное сохранение удаляет черновик', async () => {
    await editAndHitExpiredSave()
    openEditor(1)
    await screen.findByDisplayValue('Новая правка')
    const update = vi.spyOn(api, 'updateQuiz').mockResolvedValue(quiz)
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    expect(update.mock.calls[0][1].questions[0].text).toBe('Новая правка')
    await waitFor(() => expect(loadDraft(draftKey(1, 2))).toBeNull())
  })

  it('явный выход удаляет черновики вкладки', () => {
    saveDraft(draftKey(1, 2), { title: 'Т', description: '', is_public: false, questions: [] })
    clearDrafts()
    expect(loadDraft(draftKey(1, 2))).toBeNull()
  })
})

describe('R19: диалог о несохранённых правках', () => {
  it('Escape закрывает диалог, фон недоступен', async () => {
    vi.spyOn(api, 'getQuiz').mockResolvedValue(quiz)
    const router = createMemoryRouter([
      { path: '/quizzes/:id/edit', element: <Editor /> },
      { path: '/quizzes', element: <p>Мои викторины</p> },
    ], { initialEntries: ['/quizzes/2/edit'] })
    render(<RouterProvider router={router} />)
    fireEvent.change(await screen.findByDisplayValue('Исходный вопрос'), { target: { value: 'Правка' } })
    fireEvent.click(screen.getByRole('link', { name: '← Мои викторины' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(screen.getByRole('button', { name: 'Сохранить', hidden: true }).closest('[inert]')).not.toBeNull()
    fireEvent.keyDown(dialog, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(router.state.location.pathname).toBe('/quizzes/2/edit')
  })
})
