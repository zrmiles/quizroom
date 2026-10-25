import { useEffect, useState, type MutableRefObject } from 'react'

interface Props {
  endsAt: number
  totalSeconds: number
  offsetRef: MutableRefObject<number>
  big?: boolean
}

export function remainingMs(endsAt: number, offset: number, now = Date.now()): number {
  return Math.max(0, endsAt - (now + offset))
}

/** Таймер считает от серверного endsAt с поправкой на разницу часов. */
export function Timer({ endsAt, totalSeconds, offsetRef, big = false }: Props) {
  const [left, setLeft] = useState(() => remainingMs(endsAt, offsetRef.current))

  useEffect(() => {
    const tick = () => setLeft(remainingMs(endsAt, offsetRef.current))
    tick()
    const id = window.setInterval(tick, 100)
    return () => window.clearInterval(id)
  }, [endsAt, offsetRef])

  const seconds = Math.ceil(left / 1000)
  const pct = Math.min(100, (left / (totalSeconds * 1000)) * 100)
  const mm = Math.floor(seconds / 60)
  const ss = String(seconds % 60).padStart(2, '0')
  return (
    <div className={`timer${seconds <= 5 ? ' urgent' : ''}`} role="timer" aria-label={`Осталось ${seconds} секунд`}>
      <div className="timer-track" aria-hidden="true">
        <div className="timer-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="timer-num" style={big ? { fontSize: 40, minWidth: 100 } : undefined}>
        {mm}:{ss}
      </span>
    </div>
  )
}
