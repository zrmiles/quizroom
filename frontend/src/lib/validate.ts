import type { QType, QuestionDraft } from './types'

/** Та же проверка, что на сервере (backend/app/schemas.py), — чтобы ошибки были видны до сохранения. */
export function questionProblems(q: QuestionDraft): string[] {
  const p: string[] = []
  if (!q.text.trim()) p.push('Добавьте текст вопроса')
  if (q.type === 'single') {
    const filled = q.options.filter((o) => o.text.trim())
    if (filled.length < 2) p.push('Нужно хотя бы два варианта')
    if (q.options.some((o) => !o.text.trim())) p.push('Заполните или удалите пустые варианты')
    const correct = q.options.filter((o) => o.is_correct)
    if (correct.length !== 1 || !correct[0].text.trim()) p.push('Отметьте верный вариант')
  }
  if (q.type === 'number') {
    const { number_answer: a, number_min: lo, number_max: hi, number_tolerance: tol } = q
    if ([a, lo, hi, tol].some((v) => v === null || Number.isNaN(v))) p.push('Заполните ответ, шкалу и допуск')
    else {
      if (!(lo! < hi!)) p.push('«От» должно быть меньше «до»')
      else if (a! < lo! || a! > hi!) p.push('Ответ вне шкалы')
      if (!(tol! > 0)) p.push('Допуск должен быть больше нуля')
    }
  }
  if (q.type === 'order') {
    if (q.options.length < 3) p.push('Нужно хотя бы три элемента')
    if (q.options.some((o) => !o.text.trim())) p.push('Заполните или удалите пустые элементы')
  }
  return p
}

export function blankQuestion(type: QType = 'single'): QuestionDraft {
  return withType(
    {
      type,
      text: '',
      time_limit: 20,
      options: [],
      number_answer: null,
      number_min: null,
      number_max: null,
      number_tolerance: null,
      number_exact_bonus: false,
    },
    type,
  )
}

/** Переключение типа: текст сохраняем, недостающие поля заполняем разумными значениями. */
export function withType(q: QuestionDraft, type: QType): QuestionDraft {
  const next: QuestionDraft = { ...q, type }
  if (type === 'single') {
    const opts = q.options.length >= 2 ? q.options.slice(0, 4) : [0, 1, 2, 3].map(() => ({ text: '', is_correct: false }))
    const hasCorrect = opts.filter((o) => o.is_correct).length === 1
    next.options = opts.map((o) => ({ ...o, is_correct: hasCorrect ? o.is_correct : false }))
  }
  if (type === 'order') {
    const opts = q.options.length >= 3 ? q.options.slice(0, 6) : [0, 1, 2, 3].map(() => ({ text: '', is_correct: false }))
    next.options = opts.map((o) => ({ ...o, is_correct: false }))
  }
  if (type === 'number') {
    next.options = []
    next.number_min ??= 0
    next.number_max ??= 100
    next.number_answer ??= 50
    next.number_tolerance ??= 10
  }
  return next
}

/** Перед отправкой на сервер убираем служебные id. */
export function toPayload(q: QuestionDraft): QuestionDraft {
  return {
    ...q,
    id: undefined,
    text: q.text.trim(),
    options: q.options.map((o) => ({ text: o.text.trim(), is_correct: o.is_correct })),
  }
}
