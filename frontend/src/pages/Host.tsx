import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Creature } from '../components/Creature'
import { QrCode } from '../components/QrCode'
import { Timer } from '../components/Timer'
import { getToken } from '../lib/api'
import { LETTERS, TYPE_LABELS, fishPosition, formatNumber, formatPin, formatPoints, histogram, plural } from '../lib/format'
import type { HostFinal, HostReveal, PublicPlayer, PublicQuestion, RoomState } from '../lib/types'
import { useGameSocket, type GameMessage } from '../lib/useGameSocket'

interface HostState {
  phase: RoomState | 'connecting'
  title: string
  questionCount: number
  players: PublicPlayer[]
  question: PublicQuestion | null
  endsAt: number
  answered: number
  total: number
  reveal: HostReveal | null
  final: HostFinal | null
  error: string | null
  /** Ведущий закрыл вход для новых игроков. */
  locked: boolean
}

const initial: HostState = {
  phase: 'connecting', title: '', questionCount: 0, players: [], question: null, endsAt: 0, answered: 0, total: 0,
  reveal: null, final: null, error: null, locked: false,
}

export function Host() {
  const { pin = '' } = useParams()
  const [s, setS] = useState<HostState>(initial)
  const [waving, setWaving] = useState<Set<number>>(new Set())

  const onMessage = useCallback((msg: GameMessage) => {
    if (msg.type === 'lobby:wave') {
      const id = msg.player_id as number
      setWaving((w) => new Set(w).add(id))
      window.setTimeout(() => setWaving((w) => {
        const n = new Set(w)
        n.delete(id)
        return n
      }), 650)
      return
    }
    setS((prev) => {
      switch (msg.type) {
        case 'state:snapshot': {
          const reveal = (msg.reveal as HostReveal | undefined) ?? null
          return {
            ...prev,
            phase: msg.state as RoomState,
            title: msg.title as string,
            questionCount: msg.questionCount as number,
            players: msg.players as PublicPlayer[],
            question: (msg.question as PublicQuestion | undefined) ?? reveal?.question ?? null,
            endsAt: (msg.endsAt as number | undefined) ?? 0,
            answered: (msg.answered as number | undefined) ?? 0,
            total: msg.playerCount as number,
            reveal,
            final: (msg.final as HostFinal | undefined) ?? null,
            locked: Boolean(msg.locked),
          }
        }
        case 'lobby:update': {
          const players = msg.players as PublicPlayer[]
          // Игрок может зайти посреди вопроса — сразу учитываем его в «из N ответили».
          return { ...prev, players, total: prev.phase === 'question' ? players.length : prev.total,
            locked: Boolean(msg.locked) }
        }
        case 'question:start':
          return { ...prev, phase: 'question', question: msg.question as PublicQuestion, endsAt: msg.endsAt as number,
            answered: 0, total: msg.total as number, reveal: null, error: null }
        case 'question:progress':
          return { ...prev, answered: msg.answered as number, total: msg.total as number }
        case 'question:reveal':
          return { ...prev, phase: 'reveal', reveal: msg as unknown as HostReveal }
        case 'game:finished':
          return { ...prev, phase: 'finished', final: msg as unknown as HostFinal }
        case 'error':
          return { ...prev, error: String(msg.message) }
        default:
          return prev
      }
    })
  }, [])

  const { status, deniedReason, send, offsetRef } = useGameSocket(pin, 'host', getToken(), onMessage)
  const online = status === 'open'
  const cmd = (type: string, extra: Record<string, unknown> = {}) => {
    const sent = send({ type, ...extra })
    setS((p) => ({
      ...p,
      error: sent ? null : 'Нет связи с комнатой — команда не отправлена. Нажмите ещё раз, когда связь восстановится',
    }))
  }

  if (status === 'denied') {
    return (
      <main className="container page empty">
        <h1>Комната недоступна</h1>
        <p className="muted">{deniedReason ?? 'Игра закончилась или сервер перезапускался.'}</p>
        <Link to="/quizzes" className="btn btn-primary">К моим викторинам</Link>
      </main>
    )
  }

  const joinUrl = `${window.location.host}/join`
  // Ссылка с кодом: телефон сразу открывает ввод имени для этой комнаты.
  const inviteUrl = `${window.location.origin}/join?pin=${pin}`

  return (
    <div className={`screen${s.phase === 'lobby' || s.phase === 'connecting' ? '' : ' screen-light'}`}>
      <header className="row between" style={{ fontWeight: 600 }}>
        <span>{s.title || 'QuizRoom'}</span>
        <span className="row" style={{ gap: 14 }}>
          {status === 'reconnecting' && <span className="chip chip-sand" role="status">Переподключаемся…</span>}
          {s.question && (s.phase === 'question' || s.phase === 'reveal') && (
            <span>Вопрос {s.question.index + 1} из {s.question.total}</span>
          )}
          <span>PIN {formatPin(pin)}</span>
          {s.phase !== 'finished' && s.phase !== 'connecting' && (
            <button type="button" className={`btn btn-sm${s.locked ? ' btn-primary' : ''}`} disabled={!online}
              aria-pressed={s.locked} onClick={() => cmd(s.locked ? 'host:unlock' : 'host:lock')}
              title={s.locked ? 'Новые игроки не могут войти. Уже вошедшие переподключаются как обычно'
                : 'Не пускать новых игроков в комнату'}>
              {s.locked ? 'Вход закрыт · открыть' : 'Закрыть вход'}
            </button>
          )}
        </span>
      </header>
      {s.error && <div role="alert" className="alert alert-error">{s.error}</div>}

      {s.phase === 'connecting' && <p className="muted">Открываем комнату…</p>}

      {s.phase === 'lobby' && (
        <div className="row" style={{ flex: 1, alignItems: 'stretch', gap: 24 }}>
          <aside className="card stack" style={{ flex: '0 1 360px', padding: 28, gap: 16, borderRadius: 28 }}>
            <span className="small muted">{s.title} · {s.questionCount} {plural(s.questionCount, 'вопрос', 'вопроса', 'вопросов')}</span>
            <span className="display" style={{ fontSize: 36 }}>Заплывайте!</span>
            <span style={{ fontWeight: 600 }}>{joinUrl} → код комнаты</span>
            <span className="pin-big">{formatPin(pin)}</span>
            <div className="row" style={{ gap: 14, alignItems: 'center', flexWrap: 'nowrap' }}>
              <QrCode value={inviteUrl} size={132} label={`QR-код для входа в комнату ${formatPin(pin)}`} />
              <span className="small" style={{ fontWeight: 600 }}>
                Или наведите камеру телефона на код — откроется вход в эту комнату
              </span>
            </div>
            <div style={{ flex: 1 }} />
            <div className="row between" style={{ fontWeight: 700 }}>
              <span>В аквариуме</span>
              <span className="display">{s.players.length}</span>
            </div>
            <button type="button" className="btn btn-accent btn-lg" disabled={!s.players.length || !online}
              onClick={() => cmd('host:start')}>
              Начать игру
            </button>
            <span className="small muted">
              Нажмите на существо, чтобы удалить игрока: под тем же именем он вернуться не сможет
            </span>
          </aside>
          <main className="aquarium" aria-label="Игроки в комнате">
            {s.players.length === 0 && (
              <p className="muted" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
                justifyContent: 'center', fontWeight: 600, zIndex: 1 }}>
                Пока никого. Откройте {joinUrl} на телефоне и введите код
              </p>
            )}
            {s.players.map((p) => (
              <button key={p.id} type="button" className={`fish${p.connected ? '' : ' offline'}`} style={fishPosition(p.id)}
                aria-label={`Удалить игрока ${p.nickname}`} disabled={!online}
                onClick={() => window.confirm(`Удалить «${p.nickname}» из комнаты?`) && cmd('host:kick', { player_id: p.id })}>
                <Creature avatar={p.avatar} size={72} jump={waving.has(p.id)} />
                <span className="name">{p.nickname}</span>
              </button>
            ))}
          </main>
        </div>
      )}

      {s.phase === 'question' && s.question && (
        <section className="stack" style={{ flex: 1, gap: 24, maxWidth: 1200, width: '100%', margin: '0 auto' }}>
          <span className="chip chip-ink" style={{ alignSelf: 'flex-start' }}>{TYPE_LABELS[s.question.type]}</span>
          <h1 style={{ fontSize: 'clamp(30px, 4vw, 48px)' }}>{s.question.text}</h1>
          <Timer endsAt={s.endsAt} totalSeconds={s.question.time_limit} offsetRef={offsetRef} big />
          {s.question.type === 'number' ? (
            <div className="card row between" style={{ fontSize: 22, fontWeight: 700 }}>
              <span>{formatNumber(s.question.min ?? 0)}</span>
              <span className="muted small">игроки двигают ползунок</span>
              <span>{formatNumber(s.question.max ?? 0)}</span>
            </div>
          ) : (
            <div className="grid-auto" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
              {s.question.options.map((o, i) => (
                <div key={o.id} className="option" style={{ cursor: 'default', fontSize: 24 }}>
                  <span className="letter">{s.question!.type === 'order' ? '•' : LETTERS[i]}</span>
                  {o.text}
                </div>
              ))}
            </div>
          )}
          <div style={{ flex: 1 }} />
          <div className="row between">
            <span className="display" style={{ fontSize: 28 }}>
              {s.answered} <span className="muted" style={{ fontSize: 20 }}>из {s.total} ответили</span>
            </span>
            <button type="button" className="btn" disabled={!online}
              onClick={() => cmd('host:skip', { questionIndex: s.question!.index })}>Закрыть вопрос</button>
          </div>
        </section>
      )}

      {s.phase === 'reveal' && s.reveal && (
        <HostRevealView r={s.reveal} disabled={!online}
          onNext={() => cmd('host:next', { questionIndex: s.reveal!.question.index })} onEnd={() => cmd('host:end')} />
      )}

      {s.phase === 'finished' && s.final && (
        <section className="stack" style={{ flex: 1, gap: 24, alignItems: 'center', textAlign: 'center' }}>
          <span className="caption">Игра окончена</span>
          <h1 style={{ fontSize: 44 }}>Итоги</h1>
          <Podium players={s.final.leaderboard.slice(0, 3)} />
          <ol className="card stack" style={{ listStyle: 'none', margin: 0, width: 'min(560px, 100%)', textAlign: 'left' }}>
            {s.final.leaderboard.slice(3, 10).map((p) => (
              <li key={p.id} className="row between">
                <span className="row" style={{ gap: 8 }}>
                  <strong style={{ width: 24 }}>{p.rank}</strong> <Creature avatar={p.avatar} size={26} /> {p.nickname}
                </span>
                <strong>{formatPoints(p.score)}</strong>
              </li>
            ))}
            {s.final.leaderboard.length <= 3 && <li className="muted">Все участники — на пьедестале</li>}
          </ol>
          <div className="row" style={{ justifyContent: 'center' }}>
            <Link to={`/reports/${s.final.sessionId}`} className="btn btn-primary btn-lg">Открыть отчёт</Link>
            <Link to="/quizzes" className="btn btn-lg">Мои викторины</Link>
          </div>
        </section>
      )}
    </div>
  )
}

function Podium({ players }: { players: PublicPlayer[] }) {
  const order = [players[1], players[0], players[2]].filter(Boolean)
  const heights: Record<number, number> = { 1: 190, 2: 140, 3: 110 }
  return (
    <div className="row" style={{ alignItems: 'flex-end', justifyContent: 'center', gap: 12 }}>
      {order.map((p) => (
        <div key={p.id} className="stack" style={{ alignItems: 'center', gap: 8, width: 170 }}>
          <Creature avatar={p.avatar} size={p.rank === 1 ? 84 : 66} />
          <strong>{p.nickname}</strong>
          <span className="muted small">{formatPoints(p.score)}</span>
          <div className="display" style={{ width: '100%', height: heights[p.rank ?? 3], borderRadius: '16px 16px 0 0',
            background: p.rank === 1 ? 'var(--coral)' : 'var(--card)', border: '1px solid var(--line)', fontSize: 40,
            paddingTop: 12 }}>
            {p.rank}
          </div>
        </div>
      ))}
    </div>
  )
}

function HostRevealView({ r, onNext, onEnd, disabled }: {
  r: HostReveal; onNext: () => void; onEnd: () => void; disabled: boolean
}) {
  const q = r.question
  const { stats } = r
  return (
    <section className="row" style={{ flex: 1, alignItems: 'stretch', gap: 24 }}>
      <div className="card stack" style={{ flex: '999 1 560px', gap: 18, padding: 28, borderRadius: 28 }}>
        <span className="small muted" style={{ fontWeight: 600 }}>{q.text}</span>
        {q.type === 'single' && (
          <div className="stack" style={{ gap: 12 }}>
            {q.options.map((o, i) => {
              const count = stats.counts?.find((c) => c.option_id === o.id)?.count ?? 0
              const ok = o.id === r.correct.correct_option_id
              const pct = stats.answered ? Math.round((count / stats.answered) * 100) : 0
              return (
                <div key={o.id} className="stack" style={{ gap: 6 }}>
                  <div className="row between" style={{ fontSize: 20, fontWeight: ok ? 700 : 500 }}>
                    <span>{LETTERS[i]} · {o.text}{ok && ' — верный ✓'}</span>
                    <span>{count}</span>
                  </div>
                  <div className={`bar${ok ? ' good' : ''}`}><span style={{ width: `${pct}%` }} /></div>
                </div>
              )
            })}
          </div>
        )}
        {q.type === 'number' && <NumberReveal r={r} />}
        {q.type === 'order' && (
          <ol className="stack" style={{ margin: 0, paddingLeft: 28, gap: 6, fontSize: 22, fontWeight: 600 }}>
            {(r.correct.correct_order ?? []).map((id) => (
              <li key={id}>{q.options.find((o) => o.id === id)?.text}</li>
            ))}
          </ol>
        )}
        <div style={{ flex: 1 }} />
        <span className="muted">
          {q.type === 'number' ? 'Получили очки' : 'Верно'}: {stats.correct} из {stats.total}
          {q.type === 'order' && ' (весь порядок)'}
          {stats.answered < stats.total && ` · не успели: ${stats.total - stats.answered}`}
        </span>
      </div>
      <aside className="card stack" style={{ flex: '1 1 320px', padding: 24, borderRadius: 28 }}>
        <span className="caption">Таблица лидеров</span>
        <ol className="stack" style={{ listStyle: 'none', margin: 0, padding: 0, gap: 10 }}>
          {r.leaderboard.slice(0, 6).map((p) => (
            <li key={p.id} className="row between" style={{ fontSize: 18 }}>
              <span className="row" style={{ gap: 8 }}>
                <strong style={{ width: 22 }}>{p.rank}</strong>
                <Creature avatar={p.avatar} size={30} />
                {p.nickname}
              </span>
              <strong>{formatPoints(p.score)}</strong>
            </li>
          ))}
        </ol>
        <div style={{ flex: 1 }} />
        <button type="button" className="btn btn-accent btn-lg" onClick={onNext} disabled={disabled}>
          {r.isLast ? 'Показать итоги' : 'Следующий вопрос'}
        </button>
        {!r.isLast && (
          <button type="button" className="btn btn-ghost btn-sm" disabled={disabled}
            onClick={() => window.confirm('Закончить игру сейчас?') && onEnd()}>
            Закончить досрочно
          </button>
        )}
      </aside>
    </section>
  )
}

function NumberReveal({ r }: { r: HostReveal }) {
  const min = r.question.min ?? 0
  const max = r.question.max ?? 100
  const guesses = r.stats.guesses ?? []
  const bins = histogram(guesses, min, max)
  const peak = Math.max(1, ...bins)
  const answer = r.correct.answer ?? 0
  const answerPct = ((answer - min) / (max - min || 1)) * 100
  const correctBin = Math.min(bins.length - 1, Math.floor(((answer - min) / (max - min || 1)) * bins.length))
  return (
    <div className="stack" style={{ gap: 16 }}>
      <span className="display" style={{ fontSize: 'clamp(80px, 12vw, 140px)', lineHeight: 0.9, color: 'var(--reef)' }}>
        {formatNumber(answer)}
      </span>
      <div className="row muted" style={{ gap: 20 }}>
        {r.stats.average != null && <span>Средняя догадка зала: <strong>{formatNumber(r.stats.average)}</strong></span>}
        {r.stats.exact && r.stats.exact.length > 0 && <span>Точно в цель: <strong>{r.stats.exact.join(', ')}</strong></span>}
      </div>
      <div aria-hidden="true" style={{ position: 'relative', height: 180, display: 'flex', alignItems: 'flex-end', gap: 4,
        borderBottom: '2px solid var(--ink)' }}>
        {bins.map((n, i) => (
          <div key={i} style={{ flex: 1, height: `${(n / peak) * 100}%`, minHeight: n ? 6 : 0, borderRadius: '6px 6px 0 0',
            background: i === correctBin ? 'var(--reef)' : 'var(--ink)' }} />
        ))}
        <div style={{ position: 'absolute', left: `${answerPct}%`, bottom: -2, width: 3, height: 196, background: 'var(--reef)' }} />
      </div>
      <div className="row between small muted" style={{ fontWeight: 700 }}>
        <span>{formatNumber(min)}</span>
        <span>{guesses.length} {plural(guesses.length, 'догадка', 'догадки', 'догадок')}</span>
        <span>{formatNumber(max)}</span>
      </div>
    </div>
  )
}
