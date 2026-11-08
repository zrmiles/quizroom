import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useBlocker, useNavigate, useParams } from 'react-router-dom'

import { ApiError, api } from '../lib/api'
import { useCurrentUser } from '../lib/auth'
import { draftKey, loadDraft, removeDraft, saveDraft, type EditorDraft } from '../lib/draft'
import { LETTERS, TYPE_LABELS, plural } from '../lib/format'
import type { QType, QuestionDraft } from '../lib/types'
import { blankQuestion, questionProblems, toPayload, withType } from '../lib/validate'

const TIMES = [10, 20, 30, 60]

export function Editor() {
  const { id } = useParams()
  const quizId = id ? Number(id) : null
  const navigate = useNavigate()
  const [title, setTitle] = useState('Новая викторина')
  const [description, setDescription] = useState('')
  const [isPublic, setIsPublic] = useState(false)
  const [questions, setQuestions] = useState<QuestionDraft[]>([blankQuestion()])
  const [sel, setSel] = useState(0)
  const [loading, setLoading] = useState(quizId !== null)
  // Ошибка загрузки существующей викторины: редактор не показываем, иначе пустая
  // заготовка могла бы перезаписать настоящие вопросы при «Сохранить».
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState<'save' | 'launch' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  // Красные рамки — только после первой попытки сохранить, чтобы пустой вопрос не «кричал».
  const [showErrors, setShowErrors] = useState(false)
  // Правки, восстановленные из черновика вкладки (например, после истечения входа).
  const [restored, setRestored] = useState(false)
  const user = useCurrentUser()
  const key = draftKey(user?.id ?? null, quizId)

  // После первого сохранения адрес меняется на /quizzes/:id/edit — перечитывать с сервера не нужно,
  // иначе сбросится выбранный вопрос.
  const skipNextLoad = useRef(false)
  const revision = useRef(0)
  // Версия викторины на сервере, от которой идут правки (updated_at): защита от записи поверх другой вкладки.
  const version = useRef<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const navigationAllowed = useRef(false)
  const blocker = useBlocker(() => dirty && !navigationAllowed.current)

  useEffect(() => { navigationAllowed.current = false }, [quizId])

  const applyDraft = (d: EditorDraft) => {
    setTitle(d.title)
    setDescription(d.description)
    setIsPublic(d.is_public)
    setQuestions(d.questions.length ? d.questions : [blankQuestion()])
    setSel(0)
    revision.current += 1
    setDirty(true)
    setSaved(false)
    setRestored(true)
  }

  // Новая викторина: черновик восстанавливаем сразу, загружать с сервера нечего.
  useEffect(() => {
    if (quizId !== null) return
    const d = loadDraft(key)
    if (d) applyDraft(d)
  }, [key])

  // Пока есть несохранённые правки, держим их копию во вкладке.
  useEffect(() => {
    if (!dirty || loading || loadError) return
    saveDraft(key, { title, description, is_public: isPublic, questions })
  }, [dirty, loading, loadError, key, title, description, isPublic, questions])

  useEffect(() => {
    if (quizId === null) return
    if (skipNextLoad.current) {
      skipNextLoad.current = false
      return
    }
    let active = true
    setLoading(true)
    setLoadError(null)
    api
      .getQuiz(quizId)
      .then((q) => {
        if (!active) return
        setTitle(q.title)
        setDescription(q.description)
        setIsPublic(q.is_public)
        setQuestions(q.questions.length ? q.questions : [blankQuestion()])
        setSel(0)
        setDirty(false)
        setRestored(false)
        setConflict(false)
        version.current = q.updated_at
        const d = loadDraft(key)
        if (d) applyDraft(d)
      })
      .catch((e: Error) => { if (active) setLoadError(e.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [quizId, loadAttempt])

  // Браузер переспросит, если закрыть вкладку с несохранёнными правками.
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const problems = useMemo(() => questions.map(questionProblems), [questions])
  const badCount = problems.filter((p) => p.length).length
  const cur = questions[Math.min(sel, questions.length - 1)]
  const curProblems = problems[sel] ?? []
  const totalSeconds = questions.reduce((s, q) => s + q.time_limit + 10, 0)

  const markDirty = () => {
    revision.current += 1
    setDirty(true)
    setSaved(false)
  }

  const update = (patch: Partial<QuestionDraft>) => {
    setQuestions((qs) => qs.map((q, i) => (i === sel ? { ...q, ...patch } : q)))
    markDirty()
  }
  const setType = (t: QType) => {
    setQuestions((qs) => qs.map((q, i) => (i === sel ? withType(q, t) : q)))
    markDirty()
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
    markDirty()
  }
  const removeQuestion = () => {
    if (questions.length === 1) {
      setQuestions([blankQuestion()])
    } else {
      setQuestions((qs) => qs.filter((_, i) => i !== sel))
      setSel((s) => Math.max(0, s - 1))
    }
    markDirty()
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
    markDirty()
  }

  /** `force` — сохранить поверх версии, которую успели изменить в другой вкладке. */
  const save = async (force = false): Promise<number | null> => {
    // Существующую викторину можно сохранять только после успешной загрузки.
    if (quizId !== null && (loading || loadError)) return null
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
    const sentRevision = revision.current
    const payload = { title: title.trim(), description, is_public: isPublic, questions: questions.map(toPayload) }
    let quiz
    try {
      quiz = quizId === null
        ? await api.createQuiz(payload)
        : await api.updateQuiz(quizId, { ...payload, base_updated_at: force ? null : version.current })
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setConflict(true)
        return null
      }
      throw e
    }
    version.current = quiz.updated_at
    setConflict(false)
    const unchanged = sentRevision === revision.current
    setDirty(!unchanged)
    setSaved(unchanged)
    if (unchanged) {
      removeDraft(key)
      setRestored(false)
    }
    if (quizId === null) {
      skipNextLoad.current = true
      navigationAllowed.current = true
      navigate(`/quizzes/${quiz.id}/edit`, { replace: true })
    }
    if (!unchanged) setError('Пока шло сохранение, появились новые изменения. Сохраните их перед запуском')
    return unchanged ? quiz.id : null
  }

  const discardDraft = () => {
    removeDraft(key)
    setRestored(false)
    setDirty(false)
    if (quizId !== null) {
      setLoadAttempt((n) => n + 1)
      return
    }
    setTitle('Новая викторина')
    setDescription('')
    setIsPublic(false)
    setQuestions([blankQuestion()])
    setSel(0)
  }

  const onSave = async (force = false) => {
    setBusy('save')
    try {
      await save(force)
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
      const launchedRevision = revision.current
      const { pin } = await api.createSession(idToRun)
      if (revision.current !== launchedRevision) {
        // Правка появилась, пока создавалась комната: не уходим молча, чтобы её не потерять.
        // Неиспользованную комнату сервер закроет сам через несколько часов.
        setError('Пока создавалась комната, появились новые правки. Сохраните их и запустите игру снова')
        return
      }
      navigationAllowed.current = true
      navigate(`/host/${pin}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div className="container page muted">Загружаем викторину…</div>
  if (quizId !== null && loadError) {
    return (
      <main className="container page" style={{ maxWidth: 560 }}>
        <h1>Не удалось открыть викторину</h1>
        <div role="alert" className="alert alert-error">{loadError}</div>
        <p className="muted">Редактировать её можно только после загрузки — так ничего не сотрётся.</p>
        <div className="row">
          <button type="button" className="btn btn-primary" onClick={() => setLoadAttempt((n) => n + 1)}>
            Повторить загрузку
          </button>
          <Link to="/quizzes" className="btn">К моим викторинам</Link>
        </div>
      </main>
    )
  }
  const locked = busy === 'launch'

  const span = Math.max(1, (cur.number_max ?? 100) - (cur.number_min ?? 0))
  const pct = (v: number) => Math.max(0, Math.min(100, ((v - (cur.number_min ?? 0)) / span) * 100))
  const lo = pct((cur.number_answer ?? 0) - (cur.number_tolerance ?? 0))
  const hi = pct((cur.number_answer ?? 0) + (cur.number_tolerance ?? 0))
  const numOrNull = (v: string) => (v === '' ? null : Number(v))

  return (
    <div className="container" style={{ maxWidth: 1440, paddingBottom: 48 }}>
      {blocker.state === 'blocked' && (
        <div role="alertdialog" aria-modal="true" aria-label="Несохранённые изменения"
          className="leave-dialog" onKeyDown={(e) => { if (e.key === 'Escape') blocker.reset() }}>
          <section className="card stack">
            <h2>Изменения не сохранены</h2>
            <p>Если уйти, последние правки будут потеряны.</p>
            <div className="row">
              <button type="button" className="btn btn-primary" autoFocus onClick={() => blocker.reset()}>Остаться</button>
              <button type="button" className="btn" onClick={() => { removeDraft(key); blocker.proceed() }}>
                Уйти без сохранения
              </button>
            </div>
          </section>
        </div>
      )}
      {/* Пока открыт диалог, остальная страница недоступна ни мышью, ни клавиатурой. */}
      <div {...(blocker.state === 'blocked' ? { inert: '' } : {})}>
      <header className="row between" style={{ padding: '16px 0', borderBottom: '1px solid var(--line)', marginBottom: 20 }}>
        <div className="row" style={{ gap: 14 }}>
          <Link to="/quizzes" style={{ color: 'var(--ink)', fontWeight: 600, textDecoration: 'none' }}>
            ← Мои викторины
          </Link>
          <label htmlFor="quiz-title" className="sr-only">Название викторины</label>
          <input id="quiz-title" className="input" value={title} maxLength={120} disabled={locked}
            onChange={(e) => { setTitle(e.target.value); markDirty() }}
            style={{ minWidth: 260, maxWidth: 480, fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 22 }} />
          <span className="small muted" aria-live="polite">
            {saved ? 'Сохранено' : dirty ? 'Есть несохранённые изменения' : ''}
          </span>
        </div>
        <div className="row">
          {showErrors && badCount > 0 && <span className="chip chip-error">Исправьте: {badCount}</span>}
          <button type="button" className="btn" onClick={() => onSave()} disabled={busy !== null}>
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
      {conflict && (
        <div role="alert" className="alert alert-error stack" style={{ marginBottom: 16, gap: 10 }}>
          <span>
            Эту викторину уже изменили в другой вкладке или на другом устройстве. Ваши правки не потеряны:
            сохраните их поверх или загрузите версию с сервера.
          </span>
          <div className="row">
            <button type="button" className="btn btn-sm" onClick={() => onSave(true)} disabled={busy !== null}>
              Сохранить мои правки поверх
            </button>
            <button type="button" className="btn btn-sm" onClick={discardDraft} disabled={busy !== null}>
              Загрузить версию с сервера
            </button>
          </div>
        </div>
      )}
      {restored && (
        <div role="status" className="alert alert-info row between" style={{ marginBottom: 16 }}>
          <span>Восстановили правки, которые не успели сохранить. Сохраните их или верните сохранённую версию.</span>
          <button type="button" className="btn" onClick={discardDraft} disabled={busy !== null}>
            {quizId === null ? 'Начать заново' : 'Вернуть сохранённую версию'}
          </button>
        </div>
      )}

      {/* Пока создаётся комната, правки заблокированы: иначе они потерялись бы при переходе. */}
      <fieldset disabled={locked} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
      <div className="row" style={{ alignItems: 'flex-start', gap: 20 }}>
        <aside className="stack" style={{ flex: '1 1 260px', maxWidth: 320, gap: 8 }}>
          <span className="caption">Вопросы · {questions.length}</span>
          {questions.map((q, i) => (
            <button key={i} type="button" onClick={() => setSel(i)} aria-current={i === sel} aria-label={`Вопрос ${i + 1}, ${TYPE_LABELS[q.type]}: ${q.text.trim() || "без текста"}${problems[i].length ? ", есть ошибки" : ""}`}
              className="card" style={{
                display: 'flex', gap: 12, alignItems: 'flex-start', padding: 12, textAlign: 'left', cursor: 'pointer',
                border: `2px solid ${i === sel ? 'var(--coral)' : showErrors && problems[i].length ? '#FFB59E' : 'var(--line)'}`,
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
              {showErrors && problems[i].length > 0 && <span className="chip chip-error" aria-label="Есть ошибки">!</span>}
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
                    style={{ width: 44, flex: '0 0 44px', padding: 0, background: o.is_correct ? 'var(--reef)' : undefined,
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
                  <button type="button" className="btn btn-sm" style={{ width: 44, flex: '0 0 44px', padding: 0 }}
                    onClick={() => moveOption(i, -1)} disabled={i === 0} aria-label={`Выше: элемент ${i + 1}`}>↑</button>
                  <button type="button" className="btn btn-sm" style={{ width: 44, flex: '0 0 44px', padding: 0 }}
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
          {(() => {
            // До первой попытки сохранить — спокойная подсказка, после — красный список.
            const tone = !curProblems.length ? 'ok' : showErrors ? 'error' : 'hint'
            const bg = { ok: 'var(--reef-bg)', error: 'var(--error-bg)', hint: 'var(--sand)' }[tone]
            const fg = { ok: 'var(--reef-ink)', error: 'var(--error)', hint: 'var(--ink)' }[tone]
            const title = { ok: 'Вопрос готов ✓', error: 'Что поправить', hint: 'Чтобы вопрос был готов' }[tone]
            return (
              <div className="card stack" style={{ background: bg, borderColor: 'transparent', gap: 6 }}>
                <span style={{ fontWeight: 700, color: fg }}>{title}</span>
                {curProblems.map((p) => (
                  <span key={p} className="small" style={{ color: fg }}>• {p}</span>
                ))}
              </div>
            )
          })()}
          <div className="card card-water stack" style={{ gap: 2 }}>
            <span className="label">Вся игра</span>
            <span className="display" style={{ fontSize: 28 }}>≈ {Math.max(1, Math.round(totalSeconds / 60))} мин</span>
            <span className="small">
              {questions.length} {plural(questions.length, 'вопрос', 'вопроса', 'вопросов')}, с разбором после каждого
            </span>
          </div>
        </aside>
      </div>
      </fieldset>
      </div>
    </div>
  )
}
