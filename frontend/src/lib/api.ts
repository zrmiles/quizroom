import { load, remove, save } from './storage'
import type {
  Avatar,
  QuestionDraft,
  Quiz,
  QuizSummary,
  Report,
  SessionHistoryItem,
  User,
} from './types'

const TOKEN_KEY = 'qr_token'

export const getToken = () => load<string>(TOKEN_KEY)
export const setToken = (t: string | null) => (t ? save(TOKEN_KEY, t) : remove(TOKEN_KEY))

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

// Pydantic пишет ошибки полей по-английски — для форм входа подменяем их понятным текстом.
const FIELD_MESSAGES: Record<string, string> = {
  email: 'Похоже, в email опечатка',
  password: 'Пароль — от 8 до 72 символов',
  username: 'Имя — от 2 до 40 символов',
  nickname: 'Имя — до 16 символов',
}

function detailToMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string; loc?: unknown[] }
    const field = String(first.loc?.[first.loc.length - 1] ?? '')
    if (FIELD_MESSAGES[field]) return FIELD_MESSAGES[field]
    return (first.msg ?? 'Проверьте поля формы').replace(/^Value error, /, '')
  }
  return 'Что-то пошло не так. Попробуйте ещё раз'
}

async function request<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      method: init.method ?? 'GET',
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    })
  } catch {
    throw new ApiError(0, 'Нет связи с сервером. Проверьте интернет')
  }
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError(res.status, detailToMessage((data as { detail?: unknown }).detail))
  return data as T
}

interface TokenOut {
  access_token: string
  user: User
}

export interface QuizPayload {
  title: string
  description: string
  is_public: boolean
  questions: QuestionDraft[]
}

export const api = {
  register: (email: string, username: string, password: string) =>
    request<TokenOut>('/auth/register', { method: 'POST', body: { email, username, password } }),
  login: (email: string, password: string) =>
    request<TokenOut>('/auth/login', { method: 'POST', body: { email, password } }),
  me: () => request<User>('/auth/me'),

  listQuizzes: () => request<QuizSummary[]>('/quizzes'),
  getQuiz: (id: number) => request<Quiz>(`/quizzes/${id}`),
  createQuiz: (q: QuizPayload) => request<Quiz>('/quizzes', { method: 'POST', body: q }),
  updateQuiz: (id: number, q: QuizPayload) => request<Quiz>(`/quizzes/${id}`, { method: 'PUT', body: q }),
  deleteQuiz: (id: number) => request<void>(`/quizzes/${id}`, { method: 'DELETE' }),

  createSession: (quizId: number) =>
    request<{ id: number; pin: string }>('/sessions', { method: 'POST', body: { quiz_id: quizId } }),
  history: () => request<SessionHistoryItem[]>('/sessions/history'),
  sessionByPin: (pin: string) =>
    request<{ pin: string; title: string; status: string; player_count: number }>(`/sessions/${pin}`),
  join: (pin: string, nickname: string, avatar: Avatar) =>
    request<{ player_id: number; token: string; nickname: string }>(`/sessions/${pin}/join`, {
      method: 'POST',
      body: { nickname, avatar },
    }),
  report: (sessionId: number) => request<Report>(`/sessions/${sessionId}/report`),
  retry: (sessionId: number) =>
    request<{ id: number; pin: string }>(`/sessions/${sessionId}/retry`, { method: 'POST' }),
}
