import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'

import { TopBar } from '../components/TopBar'
import { useAuth } from '../lib/auth'

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { user, login, register } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = params.get('next') || '/quizzes'
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={next} replace />

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (mode === 'login') await login(email, password)
      else await register(email, username, password)
      navigate(next, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не получилось')
    } finally {
      setBusy(false)
    }
  }

  const isLogin = mode === 'login'
  const other = `${isLogin ? '/register' : '/login'}${params.get('next') ? `?next=${encodeURIComponent(next)}` : ''}`

  return (
    <>
      <TopBar />
      <main className="container page" style={{ maxWidth: 460 }}>
        <div className="stack" style={{ gap: 6 }}>
          <h1>{isLogin ? 'Вход для ведущих' : 'Регистрация ведущего'}</h1>
          <p className="muted">Аккаунт нужен, чтобы создавать викторины. Игрокам он не нужен.</p>
        </div>
        <form className="card stack" style={{ gap: 16 }} onSubmit={onSubmit} noValidate>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" className="input" type="email" autoComplete="email" required value={email}
              onChange={(e) => setEmail(e.target.value)} />
          </div>
          {!isLogin && (
            <div className="field">
              <label htmlFor="username">Как вас называть</label>
              <input id="username" className="input" autoComplete="name" required minLength={2} maxLength={40}
                value={username} onChange={(e) => setUsername(e.target.value)} />
            </div>
          )}
          <div className="field">
            <label htmlFor="password">Пароль</label>
            <input id="password" className="input" type="password" required minLength={8} maxLength={72}
              autoComplete={isLogin ? 'current-password' : 'new-password'} value={password}
              onChange={(e) => setPassword(e.target.value)} aria-describedby={isLogin ? undefined : 'pw-hint'} />
            {!isLogin && (
              <span id="pw-hint" className="small muted">Не меньше 8 символов</span>
            )}
          </div>
          {error && (
            <div role="alert" className="alert alert-error">
              {error}
            </div>
          )}
          <button type="submit" className="btn btn-primary btn-lg" disabled={busy}>
            {busy ? 'Минутку…' : isLogin ? 'Войти' : 'Создать аккаунт'}
          </button>
        </form>
        <p className="small">
          {isLogin ? 'Ещё нет аккаунта? ' : 'Уже есть аккаунт? '}
          <Link to={other}>{isLogin ? 'Зарегистрироваться' : 'Войти'}</Link>
        </p>
      </main>
    </>
  )
}
