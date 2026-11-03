import { useCallback, useEffect, useRef, useState } from 'react'

export type SocketStatus = 'connecting' | 'open' | 'reconnecting' | 'denied'

// Коды закрытия, после которых переподключаться бессмысленно.
const FINAL_CODES = new Set([4001, 4401, 4403, 4404])

// Счётчик попыток сбрасываем, только если соединение продержалось столько времени.
// Иначе сервер, который принимает и сразу закрывает соединение, получал бы повтор каждую секунду.
export const STABLE_CONNECTION_MS = 10_000

/** Задержка перед повтором: 1, 2, 4, 5, 5… с, плюс до 30% случайного разброса, чтобы телефоны не приходили разом. */
export function reconnectDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(1000 * 2 ** (attempt - 1), 5000)
  return Math.round(base * (1 + 0.3 * random()))
}

export interface GameMessage {
  type: string
  serverNow?: number
  [key: string]: unknown
}

/**
 * WebSocket к игровой комнате с автопереподключением.
 * Возвращает смещение часов сервера относительно клиента — от него считается таймер.
 */
export function useGameSocket(pin: string, role: 'host' | 'player', token: string | null,
  onMessage: (msg: GameMessage) => void) {
  const [status, setStatus] = useState<SocketStatus>('connecting')
  const [deniedReason, setDeniedReason] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const handlerRef = useRef(onMessage)
  const offsetRef = useRef(0)
  handlerRef.current = onMessage

  useEffect(() => {
    if (!token) return
    let stopped = false
    let attempt = 0
    let lastError: string | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let stableTimer: ReturnType<typeof setTimeout> | undefined

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      // Токен — первым сообщением, а не в адресе: адреса попадают в логи сервера и прокси.
      const ws = new WebSocket(`${proto}://${window.location.host}/ws/game/${pin}`)
      wsRef.current = ws
      ws.onopen = () => {
        clearTimeout(stableTimer)
        stableTimer = setTimeout(() => { attempt = 0 }, STABLE_CONNECTION_MS)
        lastError = null
        ws.send(JSON.stringify({ type: 'auth', role, token }))
        setStatus('open')
      }
      ws.onmessage = (ev) => {
        let msg: GameMessage
        try {
          msg = JSON.parse(ev.data as string) as GameMessage
        } catch {
          return
        }
        if (typeof msg.serverNow === 'number') offsetRef.current = msg.serverNow - Date.now()
        if (msg.type === 'error') lastError = String(msg.message)
        handlerRef.current(msg)
      }
      ws.onclose = (ev) => {
        clearTimeout(stableTimer)
        if (stopped) return
        if (FINAL_CODES.has(ev.code)) {
          setDeniedReason(ev.code === 4001 ? 'Ведущий удалил вас из комнаты' : lastError)
          setStatus('denied')
          return
        }
        setStatus('reconnecting')
        attempt += 1
        timer = setTimeout(connect, reconnectDelay(attempt))
      }
    }

    connect()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      clearTimeout(stableTimer)
      wsRef.current?.close()
    }
  }, [pin, role, token])

  const send = useCallback((msg: Record<string, unknown>) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
      return true
    }
    return false
  }, [])

  return { status, deniedReason, send, offsetRef }
}
