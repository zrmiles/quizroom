import { useCallback, useEffect, useState, type MutableRefObject } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'

import { Creature } from '../components/Creature'
import { Timer } from '../components/Timer'
import { LETTERS, TYPE_LABELS, formatNumber, formatPoints } from '../lib/format'
import { load, playerKey, remove, type PlayerTicket } from '../lib/storage'
import type { PlayerFinal, PlayerReveal, PublicPlayer, PublicQuestion, RoomState } from '../lib/types'
import { useGameSocket, type GameMessage } from '../lib/useGameSocket'

interface PlayState {
  phase: RoomState | 'connecting'
  title: string
  me: (PublicPlayer & { rank?: number }) | null
  playerCount: number
  question: PublicQuestion | null
  endsAt: number
  answered: boolean
  myChoice: unknown
  reveal: PlayerReveal | null
  final: PlayerFinal | null
  error: string | null
}

const initial: PlayState = {
  phase: 'connecting', title: '', me: null, playerCount: 0, question: null, endsAt: 0, answered: false,
  myChoice: null, reveal: null, final: null, error: null,
}

export function Play() {
  const { pin = '' } = useParams()
  const ticket = load<PlayerTicket>(playerKey(pin))
  const [s, setS] = useState<PlayState>(initial)
  const [jump, setJump] = useState(false)

  const onMessage = useCallback((msg: GameMessage) => {
    setS((prev) => {
      switch (msg.type) {
        case 'state:snapshot': {
          const reveal = (msg.reveal as PlayerReveal | undefined) ?? null
          return {
            ...prev,
            phase: msg.state as RoomState,
            title: msg.title as string,
            me: msg.you as PublicPlayer,
            playerCount: msg.playerCount as number,
            question: (msg.question as PublicQuestion | undefined) ?? reveal?.question ?? null,
            endsAt: (msg.endsAt as number | undefined) ?? 0,
            answered: Boolean(msg.youAnswered),
            reveal,
            final: (msg.final as PlayerFinal | undefined) ?? null,
            error: null,
          }
        }
        case 'lobby:update':
          return { ...prev, playerCount: (msg.playerCount as number) ?? prev.playerCount }
        case 'question:start':
          return { ...prev, phase: 'question', question: msg.question as PublicQuestion, endsAt: msg.endsAt as number,
            answered: false, myChoice: null, reveal: null, error: null }
        case 'answer:ack':
          return { ...prev, answered: true, error: null }
        case 'question:reveal': {
          const reveal = msg as unknown as PlayerReveal
          return { ...prev, phase: 'reveal', reveal,
            me: prev.me ? { ...prev.me, score: reveal.you.score, rank: reveal.you.rank } : prev.me }
        }
        case 'game:finished':
          return { ...prev, phase: 'finished', final: msg as unknown as PlayerFinal }
        case 'error':
          return { ...prev, error: String(msg.message) }
        default:
          return prev
      }
    })
    if (msg.type === 'lobby:wave' && (msg.player_id as number) === ticket?.playerId) {
      setJump(true)
      window.setTimeout(() => setJump(false), 650)
    }
  }, [ticket?.playerId])

  const { status, deniedReason, send, offsetRef } = useGameSocket(pin, 'player', ticket?.token ?? null, onMessage)

  useEffect(() => {
    if (status === 'denied') remove(playerKey(pin))
  }, [status, pin])

  if (!ticket) return <Navigate to={`/join?pin=${pin}`} replace />

  if (status === 'denied') {
    return (
      <main className="phone empty stack" style={{ justifyContent: 'center' }}>
        <h1>Игра недоступна</h1>
        <p className="muted">{deniedReason ?? 'Комната закрылась или код устарел.'}</p>
        <Link to="/join" className="btn btn-accent btn-lg">Ввести другой код</Link>
      </main>
    )
  }

  const answer = (value: unknown) => {
    if (!s.question || s.answered) return
    setS((p) => ({ ...p, myChoice: value }))
    send({ type: 'player:answer', questionIndex: s.question.index, value })
  }

  const me = s.me
  return (
    <main className="phone" style={s.phase === 'lobby' ? { background: 'var(--water)', maxWidth: 'none' } : undefined}>
      <div className="row between">
        <div className="row" style={{ gap: 8 }}>
          {me && <Creature avatar={me.avatar} size={30} />}
          <span style={{ fontWeight: 700, fontSize: 14 }}>
            {me ? `${me.nickname} · ${formatPoints(me.score)}` : ticket.nickname}
          </span>
        </div>
        {status !== 'open' && <span className="chip chip-sand" role="status">Переподключаемся…</span>}
        {s.question && s.phase !== 'lobby' && (
          <span className="small muted" style={{ fontWeight: 600 }}>
            {s.question.index + 1} из {s.question.total}
          </span>
        )}
      </div>

      {s.phase === 'connecting' && <p className="muted">Подключаемся к комнате…</p>}

      {s.phase === 'lobby' && me && (
        <section className="stack" style={{ flex: 1, alignItems: 'center', justifyContent: 'center', textAlign: 'center', gap: 16 }}>
          <Creature avatar={me.avatar} size={150} jump={jump} />
          <h1 style={{ fontSize: 30 }}>{me.nickname}, вы в аквариуме!</h1>
          <p>«{s.title}» · {s.playerCount} в комнате<br />Найдите себя на большом экране</p>
          <div className="card" style={{ background: 'rgba(255,255,255,0.6)', borderColor: 'transparent', width: '100%' }}>
            Ведущий начнёт, когда все соберутся
          </div>
          <button type="button" className="btn btn-primary btn-lg btn-block" onClick={() => send({ type: 'player:wave' })}>
            Помахать
          </button>
        </section>
      )}

      {s.phase === 'question' && s.question && (
        <QuestionView key={s.question.index} q={s.question} endsAt={s.endsAt} offsetRef={offsetRef}
          answered={s.answered} myChoice={s.myChoice} onAnswer={answer} error={s.error} />
      )}

      {s.phase === 'reveal' && s.reveal && <RevealView r={s.reveal} />}

      {s.phase === 'finished' && s.final && (
        <section className="stack" style={{ flex: 1, justifyContent: 'center', textAlign: 'center', gap: 16 }}>
          <span className="caption">Игра окончена</span>
          <span className="big-number">{s.final.you.rank}</span>
          <h1>место из {s.final.you.players}</h1>
          <p className="muted">
            {formatPoints(s.final.you.score)} очков · верно {s.final.you.correct} из {s.final.you.total}
          </p>
          <ol className="card stack" style={{ listStyle: 'none', margin: 0, textAlign: 'left' }}>
            {s.final.leaderboard.map((p) => (
              <li key={p.id} className="row between">
                <span className="row" style={{ gap: 8 }}>
                  <strong>{p.rank}</strong> <Creature avatar={p.avatar} size={26} /> {p.nickname}
                </span>
                <strong>{formatPoints(p.score)}</strong>
              </li>
            ))}
          </ol>
          <Link to="/" className="btn btn-lg">На главную</Link>
        </section>
      )}
    </main>
  )
}

function QuestionView({ q, endsAt, offsetRef, answered, myChoice, onAnswer, error }: {
  q: PublicQuestion
  endsAt: number
  offsetRef: MutableRefObject<number>
  answered: boolean
  myChoice: unknown
  onAnswer: (v: unknown) => void
  error: string | null
}) {
  const min = q.min ?? 0
  const max = q.max ?? 100
  const step = max - min >= 50 ? 1 : max - min >= 5 ? 0.5 : 0.1
  const [guess, setGuess] = useState(() => Math.round((min + max) / 2))
  const [order, setOrder] = useState(q.options)
  const clamp = (v: number) => Math.min(max, Math.max(min, Math.round(v / step) * step))
  const bigStep = Math.max(step, Math.round((max - min) / 10))
  const chosen = (myChoice as { option_id?: number } | null)?.option_id

  const move = (i: number, d: number) => {
    const j = i + d
    if (j < 0 || j >= order.length || answered) return
    const next = order.slice()
    ;[next[i], next[j]] = [next[j], next[i]]
    setOrder(next)
  }

  return (
    <section className="stack" style={{ flex: 1, gap: 18 }}>
      <Timer endsAt={endsAt} totalSeconds={q.time_limit} offsetRef={offsetRef} />
      <span className="chip chip-ink" style={{ alignSelf: 'flex-start' }}>{TYPE_LABELS[q.type]}</span>
      <h1 style={{ fontSize: 26, lineHeight: 1.2 }}>{q.text}</h1>

      {q.type === 'single' && (
        <div className="stack" style={{ gap: 10 }}>
          {q.options.map((o, i) => (
            <button key={o.id} type="button" className="option" aria-pressed={chosen === o.id} disabled={answered}
              onClick={() => onAnswer({ option_id: o.id })} style={answered && chosen !== o.id ? { opacity: 0.45 } : undefined}>
              <span className="letter">{LETTERS[i]}</span>
              <span>{o.text}</span>
            </button>
          ))}
        </div>
      )}

      {q.type === 'number' && (
        <div className="card stack" style={{ gap: 14 }}>
          <span className="big-number" aria-live="polite">{formatNumber(guess)}</span>
          <label htmlFor="guess" className="sr-only">Ваш ответ</label>
          <input id="guess" type="range" min={min} max={max} step={step} value={guess} disabled={answered}
            onChange={(e) => setGuess(Number(e.target.value))} />
          <div className="row between small muted" style={{ fontWeight: 700 }} aria-hidden="true">
            <span>{formatNumber(min)}</span><span>{formatNumber(max)}</span>
          </div>
          <div className="row" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)' }}>
            {[-bigStep, -step, step, bigStep].map((d) => (
              <button key={d} type="button" className="btn btn-sm" disabled={answered} onClick={() => setGuess(clamp(guess + d))}>
                {d > 0 ? '+' : '−'}{formatNumber(Math.abs(d))}
              </button>
            ))}
          </div>
        </div>
      )}

      {q.type === 'order' && (
        <ol className="stack" style={{ listStyle: 'none', margin: 0, padding: 0, gap: 8 }}>
          {order.map((o, i) => (
            <li key={o.id} className="option" style={{ cursor: 'default' }}>
              <span className="display" style={{ width: 26, fontSize: 24 }}>{i + 1}</span>
              <span style={{ flex: 1 }}>{o.text}</span>
              <button type="button" className="btn btn-sm" style={{ width: 44, padding: 0 }} disabled={answered || i === 0}
                onClick={() => move(i, -1)} aria-label={`Поднять: ${o.text}`}>↑</button>
              <button type="button" className="btn btn-sm" style={{ width: 44, padding: 0 }}
                disabled={answered || i === order.length - 1} onClick={() => move(i, 1)} aria-label={`Опустить: ${o.text}`}>↓</button>
            </li>
          ))}
        </ol>
      )}

      {error && <div role="alert" className="alert alert-error">{error}</div>}
      <div style={{ flex: 1 }} />
      {answered ? (
        <div className="alert alert-ok" role="status" style={{ textAlign: 'center' }}>Ответ принят · ждём остальных</div>
      ) : q.type === 'number' ? (
        <button type="button" className="btn btn-accent btn-lg btn-block" onClick={() => onAnswer({ number: guess })}>
          Ответить: {formatNumber(guess)}
        </button>
      ) : q.type === 'order' ? (
        <button type="button" className="btn btn-accent btn-lg btn-block" onClick={() => onAnswer({ order: order.map((o) => o.id) })}>
          Готово
        </button>
      ) : (
        <p className="small muted" style={{ textAlign: 'center' }}>Нажмите на вариант — ответ отправится сразу</p>
      )}
    </section>
  )
}

function correctText(r: PlayerReveal): string {
  const { question: q, correct: c } = r
  if (q.type === 'single') return q.options.find((o) => o.id === c.correct_option_id)?.text ?? ''
  if (q.type === 'number') return formatNumber(c.answer ?? 0)
  const byId = new Map(q.options.map((o) => [o.id, o.text]))
  return (c.correct_order ?? []).map((id) => byId.get(id)).join(' → ')
}

function RevealView({ r }: { r: PlayerReveal }) {
  const good = r.you.correct
  return (
    <section className="stack" style={{ flex: 1, gap: 16 }}>
      <div className="card stack" style={{ gap: 6, background: good ? 'var(--reef)' : r.you.answered ? 'var(--error-bg)' : 'var(--card)',
        color: good ? '#fff' : r.you.answered ? 'var(--error)' : 'var(--ink)', borderColor: 'transparent' }}>
        <span className="display" style={{ fontSize: 34 }}>
          {good ? 'Верно!' : r.you.answered ? (r.you.points > 0 ? 'Почти!' : 'Мимо') : 'Не успели'}
        </span>
        <span style={{ fontSize: 22, fontWeight: 700 }}>+{formatPoints(r.you.points)} очков</span>
        {r.you.exact && r.correct.exact_bonus && <span style={{ fontWeight: 600 }}>Точно в цель — очки удвоены</span>}
      </div>
      <div className="card stack" style={{ gap: 4 }}>
        <span className="caption">Правильный ответ</span>
        <span style={{ fontWeight: 700, fontSize: 19 }}>{correctText(r)}</span>
      </div>
      <div className="row between card">
        <span className="display" style={{ fontSize: 26 }}>{r.you.rank} место</span>
        <span style={{ fontWeight: 700 }}>{formatPoints(r.you.score)} очков</span>
      </div>
      <p className="muted small" style={{ textAlign: 'center' }}>
        {r.isLast ? 'Это был последний вопрос — ждём итоги' : 'Ведущий скоро покажет следующий вопрос'}
      </p>
    </section>
  )
}
