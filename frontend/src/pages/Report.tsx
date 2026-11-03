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
}
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
    ...p.cells.map((c) => (c.state === 'none' ? '—' : c.state === 'wrong' ? 'ошибка' : 'верно')),
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
    api.report(Number(id)).then(setR).catch((e: Error) => setError(e.message))
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
  // «Трудным» вопрос считаем, только если с ним справились меньше 80% — иначе трудных нет.
  const hardest = lowest && lowest.correct_rate < 0.8 ? lowest : null
  const mastered = questions.filter((q) => q.correct_rate >= 0.8)
  const attention = players.filter((p) => p.reconnects > 0 || p.skipped > 0)

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
            <button type="button" className="btn btn-accent" onClick={retry} disabled={busy}>
              {busy ? 'Готовим…' : 'Повторить только ошибки'}
            </button>
          </div>
        </header>
        {error && <div role="alert" className="alert alert-error">{error}</div>}

        {players.length === 0 ? (
          <div className="card empty">В этой игре не было участников.</div>
        ) : (
          <>
            <section className="grid-auto">
              <div className="card kpi"><span className="muted small">Средний результат</span>
                <span className="value">{Math.round(summary.avg_correct_rate * 100)}%</span></div>
              <div className="card kpi"><span className="muted small">Самый трудный</span>
                <span className="value">{hardest ? `Вопрос ${hardest.index + 1}` : 'Нет'}</span></div>
              <div className="card kpi"><span className="muted small">Среднее время ответа</span>
                <span className="value">{summary.avg_response_ms != null ? `${(summary.avg_response_ms / 1000).toFixed(1).replace('.', ',')} с` : '—'}</span></div>
              <div className="card kpi"><span className="muted small">Дошли до конца</span>
                <span className="value">{summary.finished_count} из {session.player_count}</span></div>
            </section>

            <section className="card stack">
              <div className="row between">
                <h2 style={{ fontSize: 20 }}>Карта ответов: ученик × вопрос</h2>
                <div className="row small" style={{ gap: 14 }}>
                  {(Object.keys(CELL) as CellState[]).map((k) => (
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
                        <th key={q.index} scope="col" title={q.text}>
                          <span className="stack" style={{ gap: 0, alignItems: 'center' }}>
                            <span style={{ color: q.correct_rate < 0.4 ? 'var(--error)' : 'var(--ink)' }}>В{q.index + 1}</span>
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
                          {p.correct}/{questions.length}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <th scope="row" style={{ textAlign: 'left' }}>Верно</th>
                      {questions.map((q) => (
                        <td key={q.index} style={{ textAlign: 'center', fontWeight: 700,
                          color: q.correct_rate < 0.4 ? 'var(--error)' : 'var(--ink)' }}>
                          {Math.round(q.correct_rate * 100)}%
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
              {hardest && hardest.correct_rate < 0.5 && (
                <div className="card stack" style={{ gap: 8 }}>
                  <span className="chip chip-error" style={{ alignSelf: 'flex-start' }}>Разобрать на занятии</span>
                  <strong>Вопрос {hardest.index + 1}: «{hardest.text}»</strong>
                  <span className="small muted">Верно ответили {Math.round(hardest.correct_rate * 100)}%.</span>
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
