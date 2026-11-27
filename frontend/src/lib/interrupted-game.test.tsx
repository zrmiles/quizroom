// @vitest-environment jsdom
// Прерванная игра: отчёт по закрытым вопросам и ссылка на него в истории (B01).
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, RouterProvider, createMemoryRouter } from 'react-router-dom'

import { Dashboard } from '../pages/Dashboard'
import { ReportPage } from '../pages/Report'
import { api } from './api'
import type { Report, SessionHistoryItem } from './types'

vi.mock('../components/TopBar', () => ({ TopBar: () => null }))
vi.mock('./auth', () => ({
  useAuth: () => ({ user: { id: 1, email: 'u@example.com', username: 'Учитель' }, logout: () => {} }),
}))

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const AV = { shape: 'blob', color: '#FFD23F', eyes: 2 } as Report['players'][number]['avatar']

function aborted(): Report {
  return {
    session: {
      id: 7, pin: '111111', title: 'Прерванная', status: 'aborted', created_at: null, finished_at: null,
      player_count: 1, question_count: 3,
    },
    summary: {
      shown_count: 2, ended_early: true, interrupted: true, avg_correct_rate: 0.5, hardest_index: 1,
      avg_response_ms: 3000, finished_count: 1, hard_rate: 0.5, retry_count: 0,
    },
    questions: [0, 1, 2].map((index) => ({
      index, type: 'single' as const, text: `В${index}`, shown: index < 2, eligible: index < 2 ? 1 : 0,
      correct_rate: index < 2 ? 0.5 : null, answered: index < 2 ? 1 : 0, avg_ms: null,
    })),
    players: [
      { id: 1, nickname: 'Аня', avatar: AV, score: 900, rank: 1, reconnects: 0, correct: 1, asked: 2, skipped: 0,
        cells: [{ state: 'fast', points: 900 }, { state: 'wrong', points: 0 }, { state: 'unshown', points: 0 }] },
    ],
  }
}

describe('отчёт прерванной игры', () => {
  it('объясняет обрыв вместо досрочного финиша', async () => {
    vi.spyOn(api, 'report').mockResolvedValue(aborted())
    const router = createMemoryRouter([{ path: '/reports/:id', element: <ReportPage /> }], {
      initialEntries: ['/reports/7'],
    })
    render(<RouterProvider router={router} />)
    await screen.findByText(/Игра прервалась.*2 из 3 вопросов, которые успели закрыть/)
    expect(screen.queryByText(/завершили досрочно/)).toBeNull()
  })
})

describe('история игр', () => {
  const item = (over: Partial<SessionHistoryItem>): SessionHistoryItem => ({
    id: 1, pin: '111111', title: 'Игра', status: 'aborted', created_at: '2026-11-20T10:00:00Z',
    player_count: 3, question_count: 5, parent_session_id: null, ...over,
  })

  it('даёт ссылку на отчёт прерванной игры, только если он есть', async () => {
    vi.spyOn(api, 'listQuizzes').mockResolvedValue([])
    vi.spyOn(api, 'history').mockResolvedValue([
      item({ id: 1, title: 'С отчётом', has_report: true }),
      item({ id: 2, title: 'Без отчёта', has_report: false }),
    ])
    render(<MemoryRouter><Dashboard /></MemoryRouter>)
    await screen.findByText('С отчётом')
    const links = screen.getAllByRole('link', { name: 'Отчёт' })
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/reports/1'])
  })
})
