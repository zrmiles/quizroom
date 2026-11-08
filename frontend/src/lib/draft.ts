// Несохранённые правки редактора живут в sessionStorage вкладки: они переживают истечение
// входа и повторный вход, но не уходят на сервер и не видны другому аккаунту.
import type { QuestionDraft } from './types'

export interface EditorDraft {
  title: string
  description: string
  is_public: boolean
  questions: QuestionDraft[]
}

const PREFIX = 'qr_draft_'
const memory = new Map<string, string>()

export const draftKey = (userId: number | null, quizId: number | null) =>
  `${PREFIX}${userId ?? 'anon'}_${quizId ?? 'new'}`

export function loadDraft(key: string): EditorDraft | null {
  let raw = memory.get(key) ?? null
  try {
    raw = window.sessionStorage.getItem(key) ?? raw
  } catch {
    // Хранилище недоступно — используем память вкладки.
  }
  if (!raw) return null
  try {
    const d = JSON.parse(raw) as EditorDraft
    return d && typeof d.title === 'string' && Array.isArray(d.questions) ? d : null
  } catch {
    return null
  }
}

export function saveDraft(key: string, draft: EditorDraft): void {
  const raw = JSON.stringify(draft)
  memory.set(key, raw)
  try {
    window.sessionStorage.setItem(key, raw)
  } catch {
    // Остаётся копия в памяти вкладки.
  }
}

export function removeDraft(key: string): void {
  memory.delete(key)
  try {
    window.sessionStorage.removeItem(key)
  } catch {
    // нечего удалять
  }
}

/** При явном выходе черновики этой вкладки удаляются: за компьютером может сесть другой человек. */
export function clearDrafts(): void {
  for (const key of [...memory.keys()]) if (key.startsWith(PREFIX)) memory.delete(key)
  try {
    const keys: string[] = []
    for (let i = 0; i < window.sessionStorage.length; i++) {
      const k = window.sessionStorage.key(i)
      if (k?.startsWith(PREFIX)) keys.push(k)
    }
    keys.forEach((k) => window.sessionStorage.removeItem(k))
  } catch {
    // нечего удалять
  }
}
