// localStorage может быть недоступен (приватный режим, блокировка) — не падаем.

export function load<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

export function save(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* ничего: без хранилища просто не переживём перезагрузку */
  }
}

export function remove(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    /* ignore */
  }
}

export interface PlayerTicket {
  token: string
  playerId: number
  nickname: string
}

export const playerKey = (pin: string) => `qr_player_${pin}`
