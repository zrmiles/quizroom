import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { TopBar } from '../components/TopBar'
import { useAuth } from '../lib/auth'

export function Account() {
  const { user, changePassword, logoutEverywhere } = useAuth()
  const navigate = useNavigate()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState<'password' | 'everywhere' | null>(null)

  const onPassword = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setDone(false)
    if (next.length < 8) return setError('Новый пароль — не меньше 8 символов')
    if (new TextEncoder().encode(next).length > 72) return setError('Новый пароль слишком длинный')
    if (next !== repeat) return setError('Пароли не совпадают')
    setBusy('password')
    try {
      await changePassword(current, next)
      setCurrent('')
      setNext('')
      setRepeat('')
      setDone(true)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const onEverywhere = async () => {
    if (!window.confirm('Выйти на всех устройствах, включая это? Идущие игры продолжатся, но экран ведущего попросит войти снова.')) return
    setError(null)
    setBusy('everywhere')
    try {
      await logoutEverywhere()
      navigate('/login', { replace: true })
    } catch (err) {
      setError((err as Error).message)
      setBusy(null)
    }
  }

  return (
    <>
      <TopBar />
      <main className="container page" style={{ maxWidth: 520 }}>
        <div className="stack" style={{ gap: 4 }}>
          <h1>Аккаунт</h1>
          <p className="muted">{user?.username} · {user?.email}</p>
        </div>

        <form className="card stack" style={{ gap: 14 }} onSubmit={onPassword} noValidate>
          <h2 style={{ fontSize: 20 }}>Сменить пароль</h2>
          <div className="field">
            <label htmlFor="current-password">Текущий пароль</label>
            <input id="current-password" className="input" type="password" autoComplete="current-password"
              value={current} onChange={(e) => setCurrent(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="new-password">Новый пароль</label>
            <input id="new-password" className="input" type="password" autoComplete="new-password" minLength={8}
              value={next} onChange={(e) => setNext(e.target.value)} required aria-describedby="new-password-hint" />
            <span id="new-password-hint" className="small muted">Не меньше 8 символов</span>
          </div>
          <div className="field">
            <label htmlFor="repeat-password">Новый пароль ещё раз</label>
            <input id="repeat-password" className="input" type="password" autoComplete="new-password"
              value={repeat} onChange={(e) => setRepeat(e.target.value)} required />
          </div>
          {error && <div role="alert" className="alert alert-error">{error}</div>}
          {done && (
            <div role="status" className="alert alert-ok">
              Пароль изменён. На других устройствах нужно будет войти заново.
            </div>
          )}
          <button type="submit" className="btn btn-primary" disabled={busy !== null || !current || !next}>
            {busy === 'password' ? 'Сохраняем…' : 'Сменить пароль'}
          </button>
        </form>

        <section className="card stack" style={{ gap: 10 }}>
          <h2 style={{ fontSize: 20 }}>Выйти на всех устройствах</h2>
          <p className="small muted">
            Если вошли на чужом компьютере и забыли выйти. Все входы, включая этот, перестанут действовать.
          </p>
          <button type="button" className="btn" onClick={onEverywhere} disabled={busy !== null}>
            {busy === 'everywhere' ? 'Выходим…' : 'Выйти везде'}
          </button>
        </section>
      </main>
    </>
  )
}
