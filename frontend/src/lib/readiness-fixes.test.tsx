// @vitest-environment jsdom
// Регрессии на находки аудита готовности от 5 ноября (R05, R09, R22 и др.).
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'

import { ReportPage } from '../pages/Report'
import { api } from './api'
import type { Report } from './types'

// Шапка не нужна для проверки отчёта, а ей нужен контекст входа.
vi.mock('../components/TopBar', () => ({ TopBar: () => null }))

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const AV = { shape: 'blob', color: '#FFD23F', eyes: 2 } as Report['players'][number]['avatar']

function report(id: number, over: Partial<Report['summary']> = {}): Report {
  return {
    session: {
      id, pin: '111111', title: `Игра ${id}`, status: 'finished', created_at: null, finished_at: null,
      player_count: 2, question_count: 3,
    },
    summary: {
      shown_count: 1, ended_early: true, avg_correct_rate: 0.5, hardest_index: 0, avg_response_ms: 4000,
      finished_count: 1, hard_rate: 0.5, retry_count: 0, ...over,
    },
    questions: [
      { index: 0, type: 'single', text: 'Первый', shown: true, eligible: 2, correct_rate: 0.5, answered: 2, avg_ms: 4000 },
      { index: 1, type: 'single', text: 'Второй', shown: false, eligible: 0, correct_rate: null, answered: 0, avg_ms: null },
      { index: 2, type: 'order', text: 'Третий', shown: false, eligible: 0, correct_rate: null, answered: 0, avg_ms: null },
    ],
    players: [
      { id: 1, nickname: 'Аня', avatar: AV, score: 900, rank: 1, reconnects: 0, correct: 1, asked: 1, skipped: 0,
        cells: [{ state: 'fast', points: 900 }, { state: 'unshown', points: 0 }, { state: 'unshown', points: 0 }] },
      { id: 2, nickname: 'Борис', avatar: AV, score: 0, rank: 2, reconnects: 0, correct: 0, asked: 1, skipped: 0,
        cells: [{ state: 'wrong', points: 0 }, { state: 'unshown', points: 0 }, { state: 'unshown', points: 0 }] },
    ],
  }
}

function open(path: string) {
  const router = createMemoryRouter([{ path: '/reports/:id', element: <ReportPage /> }], { initialEntries: [path] })
  render(<RouterProvider router={router} />)
  return router
}

describe('R05/R22: отчёт после досрочного финиша', () => {
  it('объясняет досрочный финиш, не показывает проценты по непоказанным и не даёт пустой повтор', async () => {
    vi.spyOn(api, 'report').mockResolvedValue(report(1))
    open('/reports/1')
    await screen.findByText(/завершили досрочно: показали 1 из 3 вопросов/)
    // Ровно 50% — не «трудный»: то же правило, что у повтора.
    expect(screen.getAllByText('Нет').length).toBeGreaterThan(0)
    const retry = screen.getByRole('button', { name: 'Повторять нечего' })
    expect(retry).toHaveProperty('disabled', true)
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('1/1').length).toBe(1)
  })

  it('кнопка повтора называет число вопросов', async () => {
    vi.spyOn(api, 'report').mockResolvedValue(report(1, { retry_count: 2, ended_early: false, shown_count: 3 }))
    open('/reports/1')
    expect(await screen.findByRole('button', { name: 'Повторить ошибки: 2 вопроса' })).toHaveProperty('disabled', false)
  })
})

describe('R09: смена отчёта', () => {
  it('ошибка загрузки нового отчёта не оставляет на экране старый', async () => {
    const spy = vi.spyOn(api, 'report').mockResolvedValueOnce(report(1))
    const router = open('/reports/1')
    await screen.findByText('Игра 1 · отчёт')
    spy.mockRejectedValueOnce(new Error('Игра не найдена'))
    await act(async () => { await router.navigate('/reports/2') })
    await screen.findByText('Игра не найдена')
    expect(screen.queryByText('Игра 1 · отчёт')).toBeNull()
    expect(screen.queryByRole('button', { name: /Повтор/ })).toBeNull()
  })

  it('запоздавший ответ по старому отчёту не подменяет новый', async () => {
    let resolveOld!: (r: Report) => void
    vi.spyOn(api, 'report').mockImplementation((id) =>
      id === 1 ? new Promise((r) => { resolveOld = r }) : Promise.resolve(report(2)),
    )
    const router = open('/reports/1')
    await act(async () => { await router.navigate('/reports/2') })
    await screen.findByText('Игра 2 · отчёт')
    await act(async () => { resolveOld(report(1)) })
    await waitFor(() => expect(screen.queryByText('Игра 1 · отчёт')).toBeNull())
    expect(screen.getByText('Игра 2 · отчёт')).toBeTruthy()
  })
})
