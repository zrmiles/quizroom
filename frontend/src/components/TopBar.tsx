import { Link, useNavigate } from 'react-router-dom'

import { useAuth } from '../lib/auth'
import { Creature } from './Creature'

export function Logo() {
  return (
    <Link to="/" className="logo" aria-label="QuizRoom — на главную">
      <Creature avatar={{ shape: 'box', color: '#FF7A59', eyes: 2 }} size={32} />
      <span className="logo-word">QuizRoom</span>
    </Link>
  )
}

export function TopBar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  return (
    <header className="container topbar">
      <Logo />
      <nav className="row" aria-label="Основное меню">
        <Link to="/join" className="btn btn-ghost btn-sm">
          Войти в игру
        </Link>
        {user ? (
          <>
            <Link to="/quizzes" className="btn btn-ghost btn-sm">
              Мои викторины
            </Link>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                logout()
                navigate('/')
              }}
            >
              Выйти
            </button>
          </>
        ) : (
          <Link to="/login" className="btn btn-sm">
            Войти
          </Link>
        )}
      </nav>
    </header>
  )
}
