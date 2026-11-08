import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { TopBar } from '../components/TopBar'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatDate, plural } from '../lib/format'
import type { QuizSummary, SessionHistoryItem } from '../lib/types'

const STATUS: Record<SessionHistoryItem['status'], string> = {
  lobby: 'идёт сбор',
  running: 'идёт игра',
  finished: 'завершена',
  aborted: 'прервана',
}

export function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [quizzes, setQuizzes] = useState<QuizSummary[] | null>(null)
  const [history, setHistory] = useState<SessionHistoryItem[]>([])
  const [error, setError] = useState<string | null>(null)
  // Ошибки загрузки списков — отдельно: сбой истории не должен прятать викторины, и наоборот.
  const [quizzesError, setQuizzesError] = useState<string | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  const reload = useCallback(() => {
    setQuizzesError(null)
    setHistoryError(null)
    api.listQuizzes().then(setQuizzes).catch((e: Error) => setQuizzesError(e.message))
    api.history().then(setHistory).catch((e: Error) => setHistoryError(e.message))
  }, [])

  useEffect(reload, [reload])

  const launch = async (quizId: number) => {
    setBusyId(quizId)
    setError(null)
    try {
      const { pin } = await api.createSession(quizId)
      navigate(`/host/${pin}`)
    } catch (e) {
      setError((e as Error).message)
      setBusyId(null)
    }
  }

  const remove = async (q: QuizSummary) => {
    if (!window.confirm(`Удалить «${q.title}»? Вместе с ней удалится история игр.`)) return
    try {
      await api.deleteQuiz(q.id)
      reload()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <>
      <TopBar />
      <main className="container page">
        <div className="row between">
          <div className="stack" style={{ gap: 4 }}>
            <span className="muted small">Здравствуйте, {user?.username}</span>
            <h1>Мои викторины</h1>
          </div>
          <Link to="/quizzes/new" className="btn btn-accent btn-lg">
            Создать викторину
          </Link>
        </div>

        {error && (
          <div role="alert" className="alert alert-error">
            {error}
          </div>
        )}

        {quizzesError ? (
          <div role="alert" className="alert alert-error row between">
            <span>Не удалось загрузить викторины: {quizzesError}</span>
            <button type="button" className="btn btn-sm" onClick={reload}>Повторить</button>
          </div>
        ) : quizzes === null ? (
          <p className="muted">Загружаем…</p>
        ) : quizzes.length === 0 ? (
          <div className="card empty stack" style={{ alignItems: 'center' }}>
            <h2>Пока пусто</h2>
            <p className="muted">Создайте первую викторину — это займёт пару минут.</p>
          </div>
        ) : (
          <div className="grid-auto">
            {quizzes.map((q) => (
              <article key={q.id} className="card stack" style={{ gap: 14 }}>
                <div className="stack" style={{ gap: 4 }}>
                  <h2 style={{ fontSize: 22 }}>{q.title}</h2>
                  <span className="muted small">
                    {q.question_count} {plural(q.question_count, 'вопрос', 'вопроса', 'вопросов')} · изменена{' '}
                    {formatDate(q.updated_at)}
                  </span>
                </div>
                <div className="row">
                  <button type="button" className="btn btn-accent btn-sm" disabled={!q.question_count || busyId !== null}
                    onClick={() => launch(q.id)}>
                    {busyId === q.id ? 'Открываем…' : 'Запустить'}
                  </button>
                  <Link to={`/quizzes/${q.id}/edit`} className="btn btn-sm">
                    Редактировать
                  </Link>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => remove(q)}>
                    Удалить
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}

        {historyError && (
          <div role="alert" className="alert alert-error row between">
            <span>Не удалось загрузить историю игр: {historyError}</span>
            <button type="button" className="btn btn-sm" onClick={reload}>Повторить</button>
          </div>
        )}

        {history.length > 0 && (
          <section className="stack">
            <h2 style={{ fontSize: 24 }}>Проведённые игры</h2>
            <div className="card table-wrap" style={{ padding: 8 }}>
              <table className="heat" style={{ minWidth: 560 }}>
                <thead>
                  <tr>
                    <th scope="col" style={{ textAlign: 'left' }}>Когда</th>
                    <th scope="col" style={{ textAlign: 'left' }}>Викторина</th>
                    <th scope="col">Игроков</th>
                    <th scope="col">Статус</th>
                    <th scope="col"><span className="sr-only">Действия</span></th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.id}>
                      <td style={{ padding: '8px' }}>{formatDate(h.created_at)}</td>
                      <td style={{ padding: '8px', fontWeight: 600 }}>{h.title}</td>
                      <td style={{ padding: '8px', textAlign: 'center' }}>{h.player_count}</td>
                      <td style={{ padding: '8px', textAlign: 'center' }} className="muted">{STATUS[h.status]}</td>
                      <td style={{ padding: '8px', textAlign: 'right' }}>
                        {h.status === 'finished' && <Link to={`/reports/${h.id}`}>Отчёт</Link>}
                        {(h.status === 'lobby' || h.status === 'running') && <Link to={`/host/${h.pin}`}>Вернуться</Link>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </main>
    </>
  )
}
