export const LETTERS = ['А', 'Б', 'В', 'Г', 'Д', 'Е']

export const TYPE_LABELS = { single: 'Один ответ', number: 'Угадай число', order: 'По порядку' } as const

export const formatPin = (pin: string) => `${pin.slice(0, 3)} ${pin.slice(3)}`

export const formatPoints = (n: number) => new Intl.NumberFormat('ru-RU').format(n)

export function formatNumber(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
}

export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

export function formatDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  return d.toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
}

/** Детерминированная «случайная» позиция существа в аквариуме по id игрока. */
export function fishPosition(id: number): { left: string; top: string } {
  const a = Math.abs(Math.sin(id * 12.9898) * 43758.5453) % 1
  const b = Math.abs(Math.sin(id * 78.233) * 12543.1234) % 1
  // Не дальше 80% по ширине: существо (до 84 px) с подписью не должно вылезать за край.
  return { left: `${4 + a * 76}%`, top: `${6 + b * 62}%` }
}

/** Гистограмма догадок для «угадай число». */
export function histogram(values: number[], min: number, max: number, bins = 20): number[] {
  const counts = new Array<number>(bins).fill(0)
  const span = max - min || 1
  for (const v of values) {
    const i = Math.min(bins - 1, Math.max(0, Math.floor(((v - min) / span) * bins)))
    counts[i] += 1
  }
  return counts
}
