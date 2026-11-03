import { Link, Route, Routes } from 'react-router-dom'

import { TopBar } from './components/TopBar'
import { RequireAuth } from './lib/auth'
import { AuthPage } from './pages/AuthPage'
import { Dashboard } from './pages/Dashboard'
import { Editor } from './pages/Editor'
import { Home } from './pages/Home'
import { Host } from './pages/Host'
import { Join } from './pages/Join'
import { Play } from './pages/Play'
import { ReportPage } from './pages/Report'

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<AuthPage key="login" mode="login" />} />
      <Route path="/register" element={<AuthPage key="register" mode="register" />} />
      <Route path="/join" element={<Join />} />
      <Route path="/play/:pin" element={<Play />} />
      <Route path="/quizzes" element={<RequireAuth><Dashboard /></RequireAuth>} />
      <Route path="/quizzes/new" element={<RequireAuth><Editor /></RequireAuth>} />
      <Route path="/quizzes/:id/edit" element={<RequireAuth><Editor /></RequireAuth>} />
      <Route path="/host/:pin" element={<RequireAuth><Host /></RequireAuth>} />
      <Route path="/reports/:id" element={<RequireAuth><ReportPage /></RequireAuth>} />
      <Route path="*" element={<NotFound />} />
    </Routes>
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
