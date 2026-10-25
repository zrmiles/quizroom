import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Creature } from '../components/Creature'
import { TopBar } from '../components/TopBar'
import { fishPosition } from '../lib/format'
import type { Avatar } from '../lib/types'

const HERO_FISH: { name: string; avatar: Avatar; size: number }[] = [
  { name: 'Аня', avatar: { shape: 'blob', color: '#FFD23F', eyes: 2 }, size: 70 },
  { name: 'Тимур', avatar: { shape: 'round', color: '#FF7A59', eyes: 2 }, size: 80 },
  { name: 'Маша', avatar: { shape: 'box', color: '#9B8CFF', eyes: 3 }, size: 64 },
  { name: 'Дима', avatar: { shape: 'round', color: '#5BD9A0', eyes: 1 }, size: 66 },
  { name: 'Лиза', avatar: { shape: 'blob', color: '#FF8FC7', eyes: 2 }, size: 72 },
  { name: 'Оля', avatar: { shape: 'box', color: '#4CC9F0', eyes: 2 }, size: 56 },
]

export function Home() {
  const [pin, setPin] = useState('')
  const navigate = useNavigate()

  const onJoin = (e: FormEvent) => {
    e.preventDefault()
    const digits = pin.replace(/\D/g, '')
    navigate(digits ? `/join?pin=${digits}` : '/join')
  }

  return (
    <>
      <TopBar />
      <main className="container page" style={{ gap: 64 }}>
        <section className="row" style={{ gap: 40, alignItems: 'center' }}>
          <div className="stack" style={{ flex: '1 1 420px', gap: 20 }}>
            <span className="chip chip-sand" style={{ alignSelf: 'flex-start' }}>
              Для пар, кружков и праздников
            </span>
            <h1 className="display" style={{ fontSize: 'clamp(40px, 6vw, 60px)', lineHeight: 1.02, letterSpacing: '-0.02em' }}>
              Квиз, в который хочется заплыть
            </h1>
            <p className="muted" style={{ fontSize: 19, maxWidth: 520 }}>
              Вы пишете вопросы и показываете код на экране. Игроки отвечают с телефонов, регистрироваться им не нужно.
            </p>
            <form onSubmit={onJoin} className="stack" style={{ maxWidth: 460, gap: 8 }}>
              <label htmlFor="home-pin" className="label">
                Есть код комнаты?
              </label>
              <div className="row">
                <input
                  id="home-pin"
                  className="input"
                  inputMode="numeric"
                  autoComplete="off"
                  placeholder="482 913"
                  maxLength={7}
                  value={pin}
                  onChange={(e) => setPin(e.target.value)}
                  style={{ flex: '1 1 180px', fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 22, letterSpacing: '0.08em' }}
                />
                <button type="submit" className="btn btn-accent btn-lg">
                  Войти в игру
                </button>
              </div>
            </form>
            <Link to="/quizzes/new" style={{ fontWeight: 700, color: 'var(--ink)' }}>
              Или создайте свою викторину →
            </Link>
          </div>
          <div aria-hidden="true" className="aquarium" style={{ flex: '1 1 420px', minHeight: 400 }}>
            {HERO_FISH.map((f, i) => (
              <span key={f.name} className="fish" style={{ ...fishPosition(i * 7 + 3), cursor: 'default' }}>
                <Creature avatar={f.avatar} size={f.size} />
                <span className="name">{f.name}</span>
              </span>
            ))}
          </div>
        </section>

        <section className="stack" style={{ gap: 20 }}>
          <h2 style={{ fontSize: 34 }}>Как это работает</h2>
          <div className="grid-auto">
            {[
              ['Соберите вопросы', 'Один ответ, угадай число или расставь по порядку. Таймер — на каждый вопрос.'],
              ['Покажите код на экране', 'Игроки вводят его на телефоне, собирают существо и ждут в аквариуме.'],
              ['Разберите результаты', 'Отчёт показывает, какие темы усвоены, а какие стоит повторить.'],
            ].map(([title, text], i) => (
              <div key={title} className="card stack" style={{ gap: 8 }}>
                <span className="display" style={{ fontSize: 40, color: 'var(--reef)' }}>
                  {i + 1}
                </span>
                <h3>{title}</h3>
                <p className="muted small">{text}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="stack" style={{ gap: 20 }}>
          <h2 style={{ fontSize: 34 }}>Не только «выбери ответ»</h2>
          <div className="grid-auto">
            <div className="card stack">
              <span className="chip chip-ink" style={{ alignSelf: 'flex-start' }}>Один ответ</span>
              <p className="muted small">Классика: быстрее ответил — больше очков.</p>
            </div>
            <div className="card stack">
              <span className="chip chip-ink" style={{ alignSelf: 'flex-start' }}>Угадай число</span>
              <span className="display" style={{ fontSize: 44 }}>1961</span>
              <p className="muted small">Ползунок вместо вариантов. Чем ближе, тем больше очков, точно — вдвойне.</p>
            </div>
            <div className="card stack">
              <span className="chip chip-ink" style={{ alignSelf: 'flex-start' }}>По порядку</span>
              <p className="muted small">Хронология, размеры, рейтинги — очки за каждый элемент на своём месте.</p>
            </div>
          </div>
        </section>

        <section className="card row" style={{ padding: 32, gap: 24 }}>
          <div className="stack" style={{ flex: '1 1 360px' }}>
            <h2 style={{ fontSize: 30 }}>Преподавателю — отчёт по каждому ученику</h2>
            <p className="muted">
              Карта «ученик × вопрос» показывает, кто понял тему, а кто угадывал. Одной кнопкой можно запустить повтор
              только с теми вопросами, где ошиблись.
            </p>
          </div>
          <Link to="/quizzes" className="btn btn-primary btn-lg">
            Мои викторины
          </Link>
        </section>

        <footer className="row between muted small" style={{ borderTop: '1px solid var(--line)', paddingTop: 20 }}>
          <span>QuizRoom · учебный проект, 2026</span>
          <Link to="/join" className="muted">Войти в игру по коду</Link>
        </footer>
      </main>
    </>
  )
}
