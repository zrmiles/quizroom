export type QType = 'single' | 'number' | 'order'
export type Shape = 'round' | 'blob' | 'box'

export interface User {
  id: number
  email: string
  username: string
}

export interface OptionDraft {
  id?: number
  text: string
  is_correct: boolean
}

export interface QuestionDraft {
  id?: number
  type: QType
  text: string
  time_limit: number
  options: OptionDraft[]
  number_answer: number | null
  number_min: number | null
  number_max: number | null
  number_tolerance: number | null
  number_exact_bonus: boolean
}

export interface Quiz {
  id: number
  title: string
  description: string
  is_public: boolean
  updated_at: string
  questions: QuestionDraft[]
}

export interface QuizSummary {
  id: number
  title: string
  question_count: number
  updated_at: string
}

export interface Avatar {
  shape: Shape
  color: string
  eyes: number
}

export interface PublicPlayer {
  id: number
  nickname: string
  avatar: Avatar
  connected: boolean
  score: number
  rank?: number
}

export interface PublicQuestion {
  index: number
  total: number
  type: QType
  text: string
  time_limit: number
  options: { id: number; text: string }[]
  min?: number
  max?: number
}

export interface CorrectInfo {
  correct_option_id?: number
  answer?: number
  tolerance?: number
  exact_bonus?: boolean
  correct_order?: number[]
}

export interface RevealStats {
  answered: number
  total: number
  correct: number
  counts?: { option_id: number; count: number }[]
  guesses?: number[]
  average?: number | null
  exact?: string[]
}

export interface HostReveal {
  type: 'question:reveal'
  question: PublicQuestion
  correct: CorrectInfo
  stats: RevealStats
  leaderboard: PublicPlayer[]
  isLast: boolean
}

export interface PlayerReveal {
  type: 'question:reveal'
  question: PublicQuestion
  correct: CorrectInfo
  you: {
    answered: boolean
    correct: boolean
    points: number
    score: number
    rank: number
    exact?: boolean
    value?: { option_id?: number; number?: number; order?: number[] } | null
  }
  isLast: boolean
}

export interface HostFinal {
  type: 'game:finished'
  sessionId: number
  leaderboard: PublicPlayer[]
}

export interface PlayerFinal {
  type: 'game:finished'
  leaderboard: PublicPlayer[]
  you: { score: number; rank: number; correct: number; total: number; players: number }
}

export type RoomState = 'lobby' | 'question' | 'reveal' | 'finished'

export interface SessionHistoryItem {
  id: number
  pin: string
  title: string
  status: 'lobby' | 'running' | 'finished' | 'aborted'
  created_at: string
  player_count: number
  question_count: number
  parent_session_id: number | null
}

export type CellState = 'fast' | 'slow' | 'wrong' | 'none' | 'absent' | 'unshown'

export interface Report {
  session: {
    id: number
    pin: string
    title: string
    status: string
    created_at: string | null
    finished_at: string | null
    player_count: number
    question_count: number
  }
  summary: {
    shown_count: number
    ended_early: boolean
    /** Доля верных по показанным вопросам; null — никто не мог ответить. */
    avg_correct_rate: number | null
    hardest_index: number | null
    avg_response_ms: number | null
    finished_count: number
    /** Вопрос «трудный» и попадает в повтор, если доля верных меньше этого порога. */
    hard_rate: number
    retry_count: number
  }
  questions: {
    index: number
    type: QType
    text: string
    shown: boolean
    eligible: number
    correct_rate: number | null
    answered: number
    avg_ms: number | null
  }[]
  players: {
    id: number
    nickname: string
    avatar: Avatar
    score: number
    rank: number | null
    reconnects: number
    correct: number
    /** Сколько показанных вопросов игрок мог ответить. */
    asked: number
    skipped: number
    cells: { state: CellState; points: number }[]
  }[]
}
