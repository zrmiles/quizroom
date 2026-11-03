// Память вкладки сохраняет активный вход, даже если localStorage недоступен.
const memory = new Map<string, string | null>()
const volatile = new Set<string>()

export function load<T>(key: string): T | null {
  let raw = memory.get(key) ?? null
  try {
    if (!volatile.has(key)) {
      raw = window.localStorage.getItem(key)
      memory.set(key, raw)
    }
  } catch {
    // Используем последнюю известную запись в памяти.
  }
  try {
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

export function save(key: string, value: unknown): void {
  const raw = JSON.stringify(value)
  memory.set(key, raw)
  try {
    window.localStorage.setItem(key, raw)
    volatile.delete(key)
  } catch {
    volatile.add(key)
  }
}

export function remove(key: string): void {
  memory.set(key, null)
  try {
    window.localStorage.removeItem(key)
    volatile.delete(key)
  } catch {
    volatile.add(key)
  }
}

export interface PlayerTicket {
  token: string
  playerId: number
  nickname: string
}

export const playerKey = (pin: string) => `qr_player_${pin}`
