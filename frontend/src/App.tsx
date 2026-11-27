import { Suspense, lazy, type ReactNode } from 'react'
import { Link, Route, Routes } from 'react-router-dom'

import { ErrorBoundary } from './components/ErrorBoundary'
import { TopBar } from './components/TopBar'
import { RequireAuth } from './lib/auth'
import { AuthPage } from './pages/AuthPage'
import { Home } from './pages/Home'
import { Join } from './pages/Join'
import { Play } from './pages/Play'

// Страницы ведущего грузятся по требованию: телефону игрока они не нужны, а сеть в классе бывает медленной.
const Dashboard = lazy(() => import('./pages/Dashboard').then((m) => ({ default: m.Dashboard })))
const Editor = lazy(() => import('./pages/Editor').then((m) => ({ default: m.Editor })))
const Host = lazy(() => import('./pages/Host').then((m) => ({ default: m.Host })))
const ReportPage = lazy(() => import('./pages/Report').then((m) => ({ default: m.ReportPage })))
const Account = lazy(() => import('./pages/Account').then((m) => ({ default: m.Account })))

function HostPage({ children }: { children: ReactNode }) {
  return (
    <RequireAuth>
      <Suspense fallback={<div className="container page muted">Загружаем…</div>}>{children}</Suspense>
    </RequireAuth>
  )
}

export function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<AuthPage key="login" mode="login" />} />
        <Route path="/register" element={<AuthPage key="register" mode="register" />} />
        <Route path="/join" element={<Join />} />
        <Route path="/play/:pin" element={<Play />} />
        <Route path="/quizzes" element={<HostPage><Dashboard /></HostPage>} />
        <Route path="/quizzes/new" element={<HostPage><Editor /></HostPage>} />
        <Route path="/quizzes/:id/edit" element={<HostPage><Editor /></HostPage>} />
        <Route path="/host/:pin" element={<HostPage><Host /></HostPage>} />
        <Route path="/reports/:id" element={<HostPage><ReportPage /></HostPage>} />
        <Route path="/account" element={<HostPage><Account /></HostPage>} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </ErrorBoundary>
  )
}

function NotFound() {
  return (
    <>
      <TopBar />
      <main className="container page empty">
        <h1>Такой страницы нет</h1>
        <p className="muted">Возможно, ссылка устарела.</p>
        <p>
          <Link to="/">На главную</Link>
        </p>
      </main>
    </>
  )
}
