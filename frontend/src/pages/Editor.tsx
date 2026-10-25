import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api } from '../lib/api'
import { LETTERS, TYPE_LABELS, plural } from '../lib/format'
import type { QType, QuestionDraft } from '../lib/types'
import { blankQuestion, questionProblems, toPayload, withType } from '../lib/validate'

const TIMES = [10, 20, 30, 60]

export function Editor() {
  const { id } = useParams()
  const quizId = id ? Number(id) : null
  const navigate = useNavigate()
  const [title, setTitle] = useState('Новая викторина')
  const [questions, setQuestions] = useState<QuestionDraft[]>([blankQuestion()])
  const [sel, setSel] = useState(0)
  const [loading, setLoading] = useState(quizId !== null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState<'save' | 'launch' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  // Красные рамки — только после первой попытки сохранить, чтобы пустой вопрос не «кричал».
  const [showErrors, setShowErrors] = useState(false)

  useEffect(() => {
    if (quizId === null) return
    api
      .getQuiz(quizId)
      .then((q) => {
        setTitle(q.title)
        setQuestions(q.questions.length ? q.questions : [blankQuestion()])
        setSel(0)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [quizId])

  const problems = useMemo(() => questions.map(questionProblems), [questions])
  const badCount = problems.filter((p) => p.length).length
  const cur = questions[Math.min(sel, questions.length - 1)]
  const curProblems = problems[sel] ?? []
  const totalSeconds = questions.reduce((s, q) => s + q.time_limit + 10, 0)

  const update = (patch: Partial<QuestionDraft>) => {
    setQuestions((qs) => qs.map((q, i) => (i === sel ? { ...q, ...patch } : q)))
    setDirty(true)
    setSaved(false)
  }
  const setType = (t: QType) => {
    setQuestions((qs) => qs.map((q, i) => (i === sel ? withType(q, t) : q)))
    setDirty(true)
  }
  const setOption = (i: number, patch: Partial<QuestionDraft['options'][number]>) =>
    update({ options: cur.options.map((o, j) => (j === i ? { ...o, ...patch } : o)) })
  const markCorrect = (i: number) => update({ options: cur.options.map((o, j) => ({ ...o, is_correct: j === i })) })
  const moveOption = (i: number, d: number) => {
    const j = i + d
    if (j < 0 || j >= cur.options.length) return
    const opts = cur.options.slice()
    ;[opts[i], opts[j]] = [opts[j], opts[i]]
    update({ options: opts })
  }
  const addOption = () => update({ options: [...cur.options, { text: '', is_correct: false }] })
  const removeOption = (i: number) => update({ options: cur.options.filter((_, j) => j !== i) })

  const addQuestion = () => {
    setQuestions((qs) => [...qs, blankQuestion()])
    setSel(questions.length)
    setDirty(true)
  }
  const removeQuestion = () => {
    if (questions.length === 1) {
      setQuestions([blankQuestion()])
    } else {
      setQuestions((qs) => qs.filter((_, i) => i !== sel))
      setSel((s) => Math.max(0, s - 1))
    }
    setDirty(true)
  }
  const moveQuestion = (d: number) => {
    const j = sel + d
    if (j < 0 || j >= questions.length) return
    setQuestions((qs) => {
      const next = qs.slice()
      ;[next[sel], next[j]] = [next[j], next[sel]]
      return next
    })
    setSel(j)
    setDirty(true)
  }

  const save = async (): Promise<number | null> => {
    setError(null)
    if (!title.trim()) {
      setError('Дайте викторине название')
      return null
    }
    if (badCount) {
      setShowErrors(true)
      const first = problems.findIndex((p) => p.length)
      setSel(first)
      setError(`Исправьте ${badCount} ${plural(badCount, 'вопрос', 'вопроса', 'вопросов')} — они отмечены «!»`)
      return null
    }
    const payload = { title: title.trim(), description: '', is_public: false, questions: questions.map(toPayload) }
    const quiz = quizId === null ? await api.createQuiz(payload) : await api.updateQuiz(quizId, payload)
    setDirty(false)
    setSaved(true)
    if (quizId === null) navigate(`/quizzes/${quiz.id}/edit`, { replace: true })
    return quiz.id
  }

  const onSave = async () => {
    setBusy('save')
    try {
      await save()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const onLaunch = async () => {
    setBusy('launch')
    try {
      const idToRun = dirty || quizId === null ? await save() : quizId
      if (idToRun === null) return
      const { pin } = await api.createSession(idToRun)
      navigate(`/host/${pin}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div className="container page muted">Загружаем викторину…</div>

  const span = Math.max(1, (cur.number_max ?? 100) - (cur.number_min ?? 0))
  const pct = (v: number) => Math.max(0, Math.min(100, ((v - (cur.number_min ?? 0)) / span) * 100))
  const lo = pct((cur.number_answer ?? 0) - (cur.number_tolerance ?? 0))
  const hi = pct((cur.number_answer ?? 0) + (cur.number_tolerance ?? 0))
  const numOrNull = (v: string) => (v === '' ? null : Number(v))

  return (
    <div className="container" style={{ maxWidth: 1440, paddingBottom: 48 }}>
      <header className="row between" style={{ padding: '16px 0', borderBottom: '1px solid var(--line)', marginBottom: 20 }}>
        <div className="row" style={{ gap: 14 }}>
          <Link to="/quizzes" style={{ color: 'var(--ink)', fontWeight: 600, textDecoration: 'none' }}>
            ← Мои викторины
          </Link>
          <label htmlFor="quiz-title" className="sr-only">Название викторины</label>
          <input id="quiz-title" className="input" value={title} maxLength={120}
            onChange={(e) => { setTitle(e.target.value); setDirty(true); setSaved(false) }}
            style={{ minWidth: 260, maxWidth: 480, fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 22 }} />
          <span className="small muted" aria-live="polite">
            {saved ? 'Сохранено' : dirty ? 'Есть несохранённые изменения' : ''}
          </span>
        </div>
        <div className="row">
          {badCount > 0 && <span className="chip chip-error">Исправьте: {badCount}</span>}
          <button type="button" className="btn" onClick={onSave} disabled={busy !== null}>
            {busy === 'save' ? 'Сохраняем…' : 'Сохранить'}
          </button>
          <button type="button" className="btn btn-accent" onClick={onLaunch} disabled={busy !== null}>
            {busy === 'launch' ? 'Открываем комнату…' : 'Запустить игру'}
          </button>
        </div>
      </header>

      {error && (
        <div role="alert" className="alert alert-error" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      <div className="row" style={{ alignItems: 'flex-start', gap: 20 }}>
        <aside className="stack" style={{ flex: '1 1 260px', maxWidth: 320, gap: 8 }}>
          <span className="caption">Вопросы · {questions.length}</span>
          {questions.map((q, i) => (
            <button key={i} type="button" onClick={() => setSel(i)} aria-current={i === sel} aria-label={`Вопрос ${i + 1}, ${TYPE_LABELS[q.type]}: ${q.text.trim() || "без текста"}${problems[i].length ? ", есть ошибки" : ""}`}
              className="card" style={{
                display: 'flex', gap: 12, alignItems: 'flex-start', padding: 12, textAlign: 'left', cursor: 'pointer',
                border: `2px solid ${i === sel ? 'var(--coral)' : problems[i].length ? '#FFB59E' : 'var(--line)'}`,
                font: 'inherit', color: 'inherit',
              }}>
              <span className="display" style={{ fontSize: 20, width: 22 }}>{i + 1}</span>
              <span className="stack" style={{ gap: 2, flex: 1, minWidth: 0 }}>
                <span className="small muted" style={{ fontWeight: 700 }}>
                  {TYPE_LABELS[q.type]} · {q.time_limit} с
                </span>
                <span className="small" style={{ fontWeight: 600, overflowWrap: 'anywhere' }}>
                  {q.text.trim() ? (q.text.length > 60 ? `${q.text.slice(0, 58)}…` : q.text) : <span className="muted">Без текста</span>}
                </span>
              </span>
              {problems[i].length > 0 && <span className="chip chip-error" aria-label="Есть ошибки">!</span>}
            </button>
          ))}
          <button type="button" className="btn" style={{ borderStyle: 'dashed' }} onClick={addQuestion}
            disabled={questions.length >= 50}>
            + Добавить вопрос
          </button>
        </aside>

        <main className="card stack" style={{ flex: '999 1 520px', minWidth: 0, gap: 20, padding: 24 }}>
          <div className="row between">
            <div className="row" role="group" aria-label="Тип вопроса">
              {(Object.keys(TYPE_LABELS) as QType[]).map((t) => (
                <button key={t} type="button" className="chip" aria-pressed={cur.type === t} onClick={() => setType(t)}>
                  {TYPE_LABELS[t]}
                </button>
              ))}
            </div>
            <div className="row">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => moveQuestion(-1)} disabled={sel === 0}
                aria-label="Переместить вопрос выше">↑</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => moveQuestion(1)}
                disabled={sel === questions.length - 1} aria-label="Переместить вопрос ниже">↓</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={removeQuestion}>Удалить вопрос</button>
            </div>
          </div>

          <div className="field">
            <label htmlFor="q-text">Вопрос {sel + 1}</label>
            <textarea id="q-text" className={`textarea${showErrors && !cur.text.trim() ? ' invalid' : ''}`} rows={2} maxLength={500}
              value={cur.text} placeholder="Например: в каком году…" onChange={(e) => update({ text: e.target.value })}
              style={{ fontSize: 21, fontWeight: 600 }} />
          </div>

          {cur.type === 'single' && (
            <div className="stack">
              <span className="label">Варианты — отметьте верный</span>
              {cur.options.map((o, i) => (
                <div key={i} className="row" style={{ flexWrap: 'nowrap' }}>
                  <button type="button" onClick={() => markCorrect(i)} aria-pressed={o.is_correct}
                    aria-label={`Верный ответ: вариант ${LETTERS[i]}`} className="btn btn-sm"
                    style={{ width: 44, padding: 0, background: o.is_correct ? 'var(--reef)' : undefined,
                      borderColor: o.is_correct ? 'var(--reef)' : 'var(--line)', color: '#fff' }}>
                    {o.is_correct ? '✓' : ''}
                  </button>
                  <span style={{ width: 22, fontWeight: 700 }}>{LETTERS[i]}</span>
                  <label htmlFor={`opt-${i}`} className="sr-only">Вариант {LETTERS[i]}</label>
                  <input id={`opt-${i}`} className={`input${showErrors && !o.text.trim() ? ' invalid' : ''}`} value={o.text}
                    maxLength={200} placeholder="Вариант ответа" onChange={(e) => setOption(i, { text: e.target.value })} />
                  <button type="button" className="btn btn-ghost btn-sm" aria-label={`Удалить вариант ${LETTERS[i]}`}
                    onClick={() => removeOption(i)} disabled={cur.options.length <= 2}>✕</button>
                </div>
              ))}
              {cur.options.length < 4 && (
                <button type="button" className="btn btn-sm" style={{ alignSelf: 'flex-start' }} onClick={addOption}>
                  + Вариант
                </button>
              )}
            </div>
          )}

          {cur.type === 'number' && (
            <div className="stack" style={{ gap: 16 }}>
              <div className="grid-auto" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
                <div className="field">
                  <label htmlFor="n-answer">Правильный ответ</label>
                  <input id="n-answer" type="number" className="input" value={cur.number_answer ?? ''}
                    onChange={(e) => update({ number_answer: numOrNull(e.target.value) })}
                    style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 22 }} />
                </div>
                <div className="field">
                  <label htmlFor="n-min">Шкала от</label>
                  <input id="n-min" type="number" className="input" value={cur.number_min ?? ''}
                    onChange={(e) => update({ number_min: numOrNull(e.target.value) })} />
                </div>
                <div className="field">
                  <label htmlFor="n-max">до</label>
                  <input id="n-max" type="number" className="input" value={cur.number_max ?? ''}
                    onChange={(e) => update({ number_max: numOrNull(e.target.value) })} />
                </div>
                <div className="field">
                  <label htmlFor="n-tol">0 очков, если ошибка ≥</label>
                  <input id="n-tol" type="number" className="input" min={0} value={cur.number_tolerance ?? ''}
                    onChange={(e) => update({ number_tolerance: numOrNull(e.target.value) })} />
                </div>
              </div>
              <label htmlFor="n-exact" className="row" style={{ fontWeight: 600, cursor: 'pointer' }}>
                <input id="n-exact" type="checkbox" checked={cur.number_exact_bonus}
                  onChange={(e) => update({ number_exact_bonus: e.target.checked })}
                  style={{ width: 22, height: 22, accentColor: 'var(--reef)' }} />
                Точное попадание — двойные очки
              </label>
              <div className="stack" style={{ gap: 6 }} aria-hidden="true">
                <span className="small muted" style={{ fontWeight: 700 }}>Так шкалу увидят игроки</span>
                <div style={{ position: 'relative', height: 12, borderRadius: 999, background: 'var(--line)' }}>
                  <div style={{ position: 'absolute', left: `${lo}%`, width: `${hi - lo}%`, height: 12, borderRadius: 999,
                    background: 'var(--reef-soft)' }} />
                  <div style={{ position: 'absolute', left: `calc(${pct(cur.number_answer ?? 0)}% - 2px)`, top: -6,
                    width: 4, height: 24, borderRadius: 2, background: 'var(--reef)' }} />
                </div>
                <div className="row between small muted" style={{ fontWeight: 700 }}>
                  <span>{cur.number_min}</span><span>зелёная зона — очки есть</span><span>{cur.number_max}</span>
                </div>
              </div>
            </div>
          )}

          {cur.type === 'order' && (
            <div className="stack">
              <span className="label">Запишите в правильном порядке — игрокам перемешаем</span>
              {cur.options.map((o, i) => (
                <div key={i} className="row" style={{ flexWrap: 'nowrap' }}>
                  <span className="display" style={{ width: 26, fontSize: 20 }}>{i + 1}</span>
                  <label htmlFor={`item-${i}`} className="sr-only">Элемент {i + 1}</label>
                  <input id={`item-${i}`} className={`input${showErrors && !o.text.trim() ? ' invalid' : ''}`} value={o.text}
                    maxLength={200} onChange={(e) => setOption(i, { text: e.target.value })} />
                  <button type="button" className="btn btn-sm" style={{ width: 44, padding: 0 }}
                    onClick={() => moveOption(i, -1)} disabled={i === 0} aria-label={`Выше: элемент ${i + 1}`}>↑</button>
                  <button type="button" className="btn btn-sm" style={{ width: 44, padding: 0 }}
                    onClick={() => moveOption(i, 1)} disabled={i === cur.options.length - 1}
                    aria-label={`Ниже: элемент ${i + 1}`}>↓</button>
                  <button type="button" className="btn btn-ghost btn-sm" aria-label={`Удалить элемент ${i + 1}`}
                    onClick={() => removeOption(i)} disabled={cur.options.length <= 3}>✕</button>
                </div>
              ))}
              {cur.options.length < 6 && (
                <button type="button" className="btn btn-sm" style={{ alignSelf: 'flex-start' }} onClick={addOption}>
                  + Элемент
                </button>
              )}
            </div>
          )}
        </main>

        <aside className="stack" style={{ flex: '1 1 260px', maxWidth: 340, gap: 14 }}>
          <div className="card stack">
            <span className="label">Время на ответ</span>
            <div className="row" role="group" aria-label="Время на ответ">
              {TIMES.map((t) => (
                <button key={t} type="button" className="chip" aria-pressed={cur.time_limit === t}
                  onClick={() => update({ time_limit: t })}>
                  {t} с
                </button>
              ))}
            </div>
          </div>
          <div className={`card stack`} style={{
            background: curProblems.length ? 'var(--error-bg)' : 'var(--reef-bg)', borderColor: 'transparent', gap: 6,
          }}>
            <span style={{ fontWeight: 700, color: curProblems.length ? 'var(--error)' : 'var(--reef-ink)' }}>
              {curProblems.length ? 'Что поправить' : 'Вопрос готов ✓'}
            </span>
            {curProblems.map((p) => (
              <span key={p} className="small" style={{ color: 'var(--error)' }}>• {p}</span>
            ))}
          </div>
          <div className="card card-water stack" style={{ gap: 2 }}>
            <span className="label">Вся игра</span>
            <span className="display" style={{ fontSize: 28 }}>≈ {Math.max(1, Math.round(totalSeconds / 60))} мин</span>
            <span className="small">
              {questions.length} {plural(questions.length, 'вопрос', 'вопроса', 'вопросов')}, с разбором после каждого
            </span>
          </div>
        </aside>
      </div>
    </div>
  )
}
