import type { Avatar } from '../lib/types'

export const AVATAR_COLORS = [
  { hex: '#FF7A59', label: 'Коралл' },
  { hex: '#FFD23F', label: 'Солнце' },
  { hex: '#5BD9A0', label: 'Мята' },
  { hex: '#9B8CFF', label: 'Сирень' },
  { hex: '#4CC9F0', label: 'Небо' },
  { hex: '#FF8FC7', label: 'Фламинго' },
]

export const SHAPES = [
  { id: 'round', label: 'Круг' },
  { id: 'blob', label: 'Капля' },
  { id: 'box', label: 'Кубик' },
] as const

const RADIUS = { round: '50%', blob: '62% 38% 55% 45% / 55% 48% 52% 45%', box: '24%' }

interface Props {
  avatar: Avatar
  size?: number
  jump?: boolean
}

/** Существо-аватар: форма × цвет × 1–3 глаза. Декоративно — имя всегда пишем рядом текстом. */
export function Creature({ avatar, size = 64, jump = false }: Props) {
  const eye = Math.round(size * 0.24)
  const pupil = Math.round(eye * 0.44)
  return (
    <span
      aria-hidden="true"
      className={`creature${jump ? ' jump' : ''}`}
      style={{
        width: size,
        height: size,
        borderRadius: RADIUS[avatar.shape] ?? RADIUS.round,
        background: avatar.color,
        gap: Math.max(2, Math.round(size * 0.06)),
      }}
    >
      {Array.from({ length: Math.min(3, Math.max(1, avatar.eyes)) }, (_, i) => (
        <span key={i} className="eye" style={{ width: eye, height: eye }}>
          <span className="pupil" style={{ width: pupil, height: pupil }} />
        </span>
      ))}
    </span>
  )
}
