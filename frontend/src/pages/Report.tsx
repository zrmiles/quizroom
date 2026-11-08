import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Creature } from '../components/Creature'
import { TopBar } from '../components/TopBar'
import { api } from '../lib/api'
import { formatDate, plural } from '../lib/format'
import type { CellState, Report } from '../lib/types'

const CELL: Record<CellState, { cls: string; sym: string; label: string }> = {
  fast: { cls: 'cell-fast', sym: '✓', label: 'верно и быстро' },
  slow: { cls: 'cell-slow', sym: '✓', label: 'верно, но долго' },
  wrong: { cls: 'cell-wrong', sym: '✗', label: 'ошибка' },
  none: { cls: 'cell-none', sym: '–', label: 'нет ответа' },
  absent: { cls: 'cell-absent', sym: '·', label: 'ещё не вошёл в игру' },
  unshown: { cls: 'cell-unshown', sym: '', label: 'вопрос не показывали' },
}
const CSV_CELL: Record<CellState, string> = {
  fast: 'верно', slow: 'верно', wrong: 'ошибка', none: '—', absent: 'не участвовал', unshown: 'не показан',
}
const percent = (rate: number | null) => (rate == null ? '—' : `${Math.round(rate * 100)}%`)
const KIND = { single: 'О', number: 'Ч', order: 'П' } as const

/** CSV с разделителем «;» и BOM — Excel на русской Windows открывает его без мастера импорта. */
export function reportToCsv(r: Report): string {
  // Ячейка, начинающаяся с = + - @, в Excel станет формулой — ники пишут игроки, поэтому экранируем.
  const esc = (v: string | number) => {
    let s = String(v)
    if (typeof v === 'string' && /^[=+\-@\t\r]/.test(s)) s = `'${s}`
    return `"${s.replace(/"/g, '""')}"`
  }
  const head = ['Место', 'Игрок', 'Очки', 'Верно', ...r.questions.map((q) => `В${q.index + 1}`)]
  const rows = r.players.map((p) => [
    p.rank ?? '',
    p.nickname,
    p.score,
    p.correct,
    ...p.cells.map((c) => CSV_CELL[c.state]),
  ])
  return '﻿' + [head, ...rows].map((row) => row.map(esc).join(';')).join('\r\n')
}

export function ReportPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [r, setR] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    // Смена отчёта: старые данные убираем сразу, ответ на прежний запрос игнорируем.
    let active = true
    setR(null)
    setError(null)
    setBusy(false)
    api.report(Number(id))
      .then((data) => { if (active) setR(data) })
      .catch((e: Error) => { if (active) setError(e.message) })
    return () => { active = false }
  }, [id])

  const retry = async () => {
    if (!r) return
    setBusy(true)
    setError(null)
    try {
      const { pin } = await api.retry(r.session.id)
      navigate(`/host/${pin}`)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  const download = () => {
    if (!r) return
    const blob = new Blob([reportToCsv(r)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${r.session.title} — отчёт.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (!r) {
    return (
      <>
        <TopBar />
        <main className="container page">
          {error ? <div role="alert" className="alert alert-error">{error}</div> : <p className="muted">Собираем отчёт…</p>}
        </main>
      </>
    )
  }

  const { summary, questions, players, session } = r
  const lowest = summary.hardest_index != null ? questions[summary.hardest_index] : null
  // «Трудный» — то же правило, по которому вопросы попадают в «повторить только ошибки».
  const hardest = lowest && lowest.correct_rate != null && lowest.correct_rate < summary.hard_rate ? lowest : null
  const mastered = questions.filter((q) => q.correct_rate != null && q.correct_rate >= 0.8)
  const attention = players.filter((p) => p.reconnects > 0 || p.skipped > 0)
  const usedStates = new Set(players.flatMap((p) => p.cells.map((c) => c.state)))
  const legend = (Object.keys(CELL) as CellState[]).filter(
    (k) => usedStates.has(k) || ['fast', 'slow', 'wrong', 'none'].includes(k),
  )
  const hardPercent = Math.round(summary.hard_rate * 100)

  return (
    <>
      <TopBar />
      <main className="container page">
        <header className="row between" style={{ alignItems: 'flex-end' }}>
          <div className="stack" style={{ gap: 4 }}>
            <Link to="/quizzes" className="small muted" style={{ textDecoration: 'none' }}>← Мои игры</Link>
            <h1>{session.title} · отчёт</h1>
            <span className="small muted">
              {formatDate(session.finished_at ?? session.created_at)} · {session.question_count}{' '}
              {plural(session.question_count, 'вопрос', 'вопроса', 'вопросов')} · {session.player_count}{' '}
              {plural(session.player_count, 'участник', 'участника', 'участников')}
            </span>
          </div>
          <div className="row">
            <button type="button" className="btn" onClick={download}>Скачать для Excel</button>
            <button
              type="button"
              className="btn btn-accent"
              onClick={retry}
              disabled={busy || summary.retry_count === 0}
              title={`В повтор попадут вопросы, где верно ответили меньше ${hardPercent}%`}
            >
              {busy
                ? 'Готовим…'
                : summary.retry_count > 0
                  ? `Повторить ошибки: ${summary.retry_count} ${plural(summary.retry_count, 'вопрос', 'вопроса', 'вопросов')}`
                  : 'Повторять нечего'}
            </button>
          </div>
        </header>
        {error && <div role="alert" className="alert alert-error">{error}</div>}
        {summary.ended_early && (
          <div role="status" className="alert alert-info">
            Игру завершили досрочно: показали {summary.shown_count} из {session.question_count}{' '}
            {plural(session.question_count, 'вопроса', 'вопросов', 'вопросов')}. Непоказанные вопросы не входят
            в средний результат и в повтор.
          </div>
        )}

        {players.length === 0 ? (
          <div className="card empty">В этой игре не было участников.</div>
        ) : (
          <>
            <section className="grid-auto">
              <div className="card kpi"><span className="muted small">Средний результат</span>
                <span className="value">{percent(summary.avg_correct_rate)}</span></div>
              <div className="card kpi"><span className="muted small">Самый трудный</span>
                <span className="value">{hardest ? `Вопрос ${hardest.index + 1}` : 'Нет'}</span></div>
              <div className="card kpi"><span className="muted small">Среднее время ответа</span>
                <span className="value">{summary.avg_response_ms != null ? `${(summary.avg_response_ms / 1000).toFixed(1).replace('.', ',')} с` : '—'}</span></div>
              <div className="card kpi"><span className="muted small">Ответили на последний вопрос</span>
                <span className="value">{summary.finished_count} из {session.player_count}</span></div>
            </section>

            <section className="card stack">
              <div className="row between">
                <h2 style={{ fontSize: 20 }}>Карта ответов: ученик × вопрос</h2>
                <div className="row small" style={{ gap: 14 }}>
                  {legend.map((k) => (
                    <span key={k} className="row" style={{ gap: 6 }}>
                      <span className={CELL[k].cls} style={{ width: 22, height: 22, borderRadius: 6, display: 'inline-flex',
                        alignItems: 'center', justifyContent: 'center', fontWeight: 700 }}>{CELL[k].sym}</span>
                      {CELL[k].label}
                    </span>
                  ))}
                </div>
              </div>
              <div className="table-wrap">
                <table className="heat">
                  <thead>
                    <tr>
                      <th scope="col" style={{ textAlign: 'left' }}>Ученик</th>
                      {questions.map((q) => (
                        <th key={q.index} scope="col" title={q.shown ? q.text : `${q.text} (не показывали)`}>
                          <span className="stack" style={{ gap: 0, alignItems: 'center' }}>
                            <span style={{ color: !q.shown ? 'var(--muted)'
                              : q.correct_rate != null && q.correct_rate < 0.4 ? 'var(--error)' : 'var(--ink)' }}>
                              В{q.index + 1}
                            </span>
                            <span style={{ fontSize: 11 }}>{KIND[q.type]}</span>
                          </span>
                        </th>
                      ))}
                      <th scope="col" style={{ textAlign: 'right' }}>Итог</th>
                    </tr>
                  </thead>
                  <tbody>
                    {players.map((p) => (
                      <tr key={p.id}>
                        <th scope="row" style={{ textAlign: 'left', whiteSpace: 'nowrap', color: 'var(--ink)' }}>
                          <span className="row" style={{ gap: 8, flexWrap: 'nowrap' }}>
                            <Creature avatar={p.avatar} size={26} /> {p.nickname}
                          </span>
                        </th>
                        {p.cells.map((c, i) => (
                          <td key={i} className={`cell ${CELL[c.state].cls}`}>
                            <span aria-hidden="true">{CELL[c.state].sym}</span>
                            <span className="sr-only">{CELL[c.state].label}</span>
                          </td>
                        ))}
                        <td style={{ textAlign: 'right', fontFamily: 'var(--font-display)', fontWeight: 700, padding: '0 8px' }}>
                          {p.correct}/{p.asked}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <th scope="row" style={{ textAlign: 'left' }}>Верно</th>
                      {questions.map((q) => (
                        <td key={q.index} style={{ textAlign: 'center', fontWeight: 700,
                          color: q.correct_rate != null && q.correct_rate < 0.4 ? 'var(--error)' : 'var(--ink)' }}>
                          {percent(q.correct_rate)}
                        </td>
                      ))}
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </div>
              <span className="small muted">
                О — один ответ, Ч — угадай число (верно = получил очки), П — по порядку (верно = все на месте)
              </span>
            </section>

            <section className="grid-auto" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
              {hardest && hardest.correct_rate != null && (
                <div className="card stack" style={{ gap: 8 }}>
                  <span className="chip chip-error" style={{ alignSelf: 'flex-start' }}>Разобрать на занятии</span>
                  <strong>Вопрос {hardest.index + 1}: «{hardest.text}»</strong>
                  <span className="small muted">
                    Верно ответили {percent(hardest.correct_rate)}: меньше {hardPercent}%, поэтому вопрос войдёт в повтор.
                  </span>
                </div>
              )}
              {mastered.length > 0 && (
                <div className="card stack" style={{ gap: 8 }}>
                  <span className="chip chip-reef" style={{ alignSelf: 'flex-start' }}>Усвоено</span>
                  <strong>
                    {plural(mastered.length, 'Вопрос', 'Вопросы', 'Вопросы')} {mastered.map((q) => q.index + 1).join(', ')}
                  </strong>
                  <span className="small muted">Верно ответили 80% и больше — можно не повторять.</span>
                </div>
              )}
              {attention.length > 0 && (
                <div className="card stack" style={{ gap: 8 }}>
                  <span className="chip chip-sand" style={{ alignSelf: 'flex-start' }}>Обратить внимание</span>
                  <strong>{attention.slice(0, 4).map((p) => p.nickname).join(', ')}</strong>
                  <span className="small muted">Пропускали вопросы или переподключались — возможно, проблемы со связью.</span>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </>
  )
}
