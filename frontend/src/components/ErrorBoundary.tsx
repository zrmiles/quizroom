import { Component, type ErrorInfo, type ReactNode } from 'react'

interface State {
  error: Error | null
}

/**
 * Ошибка при отрисовке не оставляет белый экран (на проекторе посреди игры это худший исход):
 * показываем объяснение и кнопку, которая перезагружает страницу — игра переподключится сама.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Ошибка интерфейса', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="container page empty stack" role="alert" style={{ alignItems: 'center' }}>
        <h1>Что-то пошло не так</h1>
        <p className="muted">Страница споткнулась. Если шла игра, после обновления вы вернётесь в неё с теми же очками.</p>
        <div className="row" style={{ justifyContent: 'center' }}>
          <button type="button" className="btn btn-primary btn-lg" onClick={() => window.location.reload()}>
            Обновить страницу
          </button>
          <a href="/" className="btn btn-lg">На главную</a>
        </div>
      </main>
    )
  }
}
