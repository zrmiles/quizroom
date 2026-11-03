import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { ApiError, api, getToken, setToken } from './api'
import type { User } from './types'

interface AuthValue {
  user: User | null
  ready: boolean
  restoreError: string | null
  retryRestore: () => void
  login: (email: string, password: string) => Promise<void>
  register: (email: string, username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const [restoreError, setRestoreError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const restoreEpoch = useRef(0)
  const retryRestore = useCallback(() => setAttempt((n) => n + 1), [])

  useEffect(() => {
    let active = true
    const epoch = ++restoreEpoch.current
    const current = () => active && epoch === restoreEpoch.current
    setRestoreError(null)
    if (!getToken()) {
      setReady(true)
      return
    }
    setReady(false)
    api
      .me()
      .then((u) => { if (current()) setUser(u) })
      .catch((e: Error) => {
        if (!current()) return
        if (e instanceof ApiError && e.status === 401) {
          setToken(null)
          setUser(null)
        } else setRestoreError(e.message)
      })
      .finally(() => { if (current()) setReady(true) })
    return () => { active = false }
  }, [attempt])

  // Сервер ответил 401 на любой запрос — выходим, чтобы RequireAuth отправил на страницу входа.
  useEffect(() => {
    const onUnauthorized = () => setUser(null)
    window.addEventListener('qr:unauthorized', onUnauthorized)
    return () => window.removeEventListener('qr:unauthorized', onUnauthorized)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login(email, password)
    restoreEpoch.current += 1
    setToken(res.access_token)
    setUser(res.user)
    setRestoreError(null)
    setReady(true)
  }, [])

  const register = useCallback(async (email: string, username: string, password: string) => {
    const res = await api.register(email, username, password)
    restoreEpoch.current += 1
    setToken(res.access_token)
    setUser(res.user)
    setRestoreError(null)
    setReady(true)
  }, [])

  const logout = useCallback(() => {
    restoreEpoch.current += 1
    setToken(null)
    setUser(null)
    setRestoreError(null)
  }, [])

  const value = useMemo(() => ({ user, ready, restoreError, retryRestore, login, register, logout }),
    [user, ready, restoreError, retryRestore, login, register, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth вне AuthProvider')
  return ctx
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready, restoreError, retryRestore } = useAuth()
  const location = useLocation()
  if (!ready) return <div className="container page muted">Загружаем…</div>
  if (restoreError) return (
    <main className="container page">
      <div role="alert" className="alert alert-error">{restoreError}</div>
      <button type="button" className="btn" onClick={retryRestore}>Попробовать снова</button>
    </main>
  )
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />
  return <>{children}</>
}
