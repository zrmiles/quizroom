import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { AVATAR_COLORS, Creature, SHAPES } from '../components/Creature'
import { Logo } from '../components/TopBar'
import { api } from '../lib/api'
import { load, playerKey, remove, save, type PlayerTicket } from '../lib/storage'
import type { Avatar, Shape } from '../lib/types'

const AVATAR_KEY = 'qr_avatar'

export function Join() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [pin, setPin] = useState((params.get('pin') ?? '').replace(/\D/g, '').slice(0, 6))
  const [room, setRoom] = useState<{ pin: string; title: string; player_count: number } | null>(null)
  const [nickname, setNickname] = useState(() => load<{ nickname: string }>(AVATAR_KEY)?.nickname ?? '')
  const [avatar, setAvatar] = useState<Avatar>(
    () => load<{ avatar: Avatar }>(AVATAR_KEY)?.avatar ?? { shape: 'round', color: '#9B8CFF', eyes: 2 },
  )
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Уже входили в эту комнату с этого устройства — предложим продолжить или зайти другим игроком.
  const [existing, setExisting] = useState<PlayerTicket | null>(null)

  // Код, который сейчас в поле: ответ по старому коду не должен открыть другую комнату.
  const currentPin = useRef(pin)
  currentPin.current = pin

  const checkPin = async (code: string) => {
    setError(null)
    setBusy(true)
    try {
      const info = await api.sessionByPin(code)
      if (currentPin.current !== code) return
      setExisting(load<PlayerTicket>(playerKey(code)))
      setRoom(info)
    } catch (e) {
      if (currentPin.current === code) setError((e as Error).message)
    } finally {
      if (currentPin.current === code) setBusy(false)
    }
  }

  // Ссылка вида /join?pin=482913 сразу проверяет код.
  useEffect(() => {
    if (pin.length === 6) void checkPin(pin)
  }, [])

  const onPin = (e: FormEvent) => {
    e.preventDefault()
    if (pin.length !== 6) {
      setError('В коде 6 цифр')
      return
    }
    void checkPin(pin)
  }

  const onJoin = async (e: FormEvent) => {
    e.preventDefault()
    if (!room) return
    if (!nickname.trim()) {
      setError('Введите имя')
      return
    }
    setError(null)
    setBusy(true)
    try {
      const res = await api.join(room.pin, nickname.trim(), avatar)
      save(playerKey(room.pin), { token: res.token, playerId: res.player_id, nickname: res.nickname } satisfies PlayerTicket)
      save(AVATAR_KEY, { nickname: nickname.trim(), avatar })
      navigate(`/play/${room.pin}`)
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <main className="phone">
      <Logo />
      {room && existing ? (
        <section className="stack" style={{ gap: 16, flex: 1 }}>
          <div className="stack" style={{ gap: 4 }}>
            <span className="muted small">«{room.title}»</span>
            <h1 style={{ fontSize: 30 }}>Вы уже в этой игре</h1>
            <p className="muted">С этого устройства заходили как «{existing.nickname}».</p>
          </div>
          <div style={{ flex: 1 }} />
          <button type="button" className="btn btn-accent btn-lg btn-block" onClick={() => navigate(`/play/${room.pin}`)}>
            Продолжить как {existing.nickname}
          </button>
          <button type="button" className="btn btn-lg btn-block" onClick={() => {
            remove(playerKey(room.pin))
            setExisting(null)
          }}>
            Войти другим игроком
          </button>
        </section>
      ) : !room ? (
        <form className="stack" style={{ gap: 20, flex: 1 }} onSubmit={onPin}>
          <div className="stack" style={{ gap: 6 }}>
            <h1 style={{ fontSize: 32 }}>Введите код комнаты</h1>
            <p className="muted">Он на большом экране у ведущего</p>
          </div>
          <label htmlFor="pin" className="sr-only">Код комнаты, 6 цифр</label>
          <input
            id="pin"
            className={`input${error ? ' invalid' : ''}`}
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            placeholder="000000"
            value={pin}
            onChange={(e) => {
              setPin(e.target.value.replace(/\D/g, '').slice(0, 6))
              setError(null)
              setBusy(false)
            }}
            style={{ height: 72, textAlign: 'center', fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 40,
              letterSpacing: '0.2em' }}
          />
          {error && <div role="alert" className="alert alert-error">{error}</div>}
          <div style={{ flex: 1 }} />
          <button type="submit" className="btn btn-accent btn-lg btn-block" disabled={busy || pin.length !== 6}>
            {busy ? 'Ищем комнату…' : 'Дальше'}
          </button>
        </form>
      ) : (
        <form className="stack" style={{ gap: 18, flex: 1 }} onSubmit={onJoin}>
          <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }}
            onClick={() => { setRoom(null); setError(null) }}>
            ← Другой код
          </button>
          <div className="stack" style={{ gap: 4 }}>
            <span className="muted small">«{room.title}» · {room.player_count} уже в комнате</span>
            <h1 style={{ fontSize: 30 }}>Кто поплывёт?</h1>
          </div>
          <div className="card-water card stack" style={{ alignItems: 'center', gap: 10, padding: 24 }}>
            <Creature avatar={avatar} size={110} />
            <span className="chip">{nickname.trim() || 'Ваше имя'}</span>
          </div>
          <div className="field">
            <label htmlFor="nick">Имя в игре</label>
            <input id="nick" className="input" maxLength={16} autoComplete="nickname" placeholder="Например, Маша К."
              value={nickname} onChange={(e) => setNickname(e.target.value)} />
          </div>
          <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 8 }}>
            <legend className="label" style={{ marginBottom: 8 }}>Цвет</legend>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              {AVATAR_COLORS.map((c) => (
                <button key={c.hex} type="button" aria-label={c.label} aria-pressed={avatar.color === c.hex}
                  onClick={() => setAvatar({ ...avatar, color: c.hex })}
                  style={{ width: 44, height: 44, borderRadius: '50%', cursor: 'pointer', background: c.hex,
                    border: `3px solid ${avatar.color === c.hex ? 'var(--ink)' : '#fff'}` }} />
              ))}
            </div>
          </fieldset>
          <div className="row" style={{ gap: 16 }}>
            <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 8, flex: '1 1 200px' }}>
              <legend className="label" style={{ marginBottom: 8 }}>Форма</legend>
              <div className="row">
                {SHAPES.map((s) => (
                  <button key={s.id} type="button" className="chip" aria-pressed={avatar.shape === s.id}
                    onClick={() => setAvatar({ ...avatar, shape: s.id as Shape })}>
                    {s.label}
                  </button>
                ))}
              </div>
            </fieldset>
            <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 8 }}>
              <legend className="label" style={{ marginBottom: 8 }}>Глаза</legend>
              <div className="row">
                {[1, 2, 3].map((n) => (
                  <button key={n} type="button" className="chip" aria-pressed={avatar.eyes === n}
                    onClick={() => setAvatar({ ...avatar, eyes: n })}>
                    {n}
                  </button>
                ))}
              </div>
            </fieldset>
          </div>
          {error && <div role="alert" className="alert alert-error">{error}</div>}
          <div style={{ flex: 1 }} />
          <button type="submit" className="btn btn-accent btn-lg btn-block" disabled={busy || !nickname.trim()}>
            {busy ? 'Заплываем…' : 'В аквариум'}
          </button>
        </form>
      )}
    </main>
  )
}
