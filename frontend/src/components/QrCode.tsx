import qrcode from 'qrcode-generator'
import { useMemo } from 'react'

/** QR-код в виде SVG: один путь из тёмных модулей, без картинок и внешних запросов. */
export function QrCode({ value, size = 200, label }: { value: string; size?: number; label: string }) {
  const { count, path } = useMemo(() => {
    const qr = qrcode(0, 'M')
    qr.addData(value)
    qr.make()
    const n = qr.getModuleCount()
    let d = ''
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c} ${r}h1v1h-1z`
    }
    return { count: n, path: d }
  }, [value])
  // Поле в 4 модуля по краям — без него камеры телефонов распознают код хуже.
  const quiet = 4
  return (
    <svg role="img" aria-label={label} width={size} height={size} shapeRendering="crispEdges"
      viewBox={`${-quiet} ${-quiet} ${count + quiet * 2} ${count + quiet * 2}`} style={{ background: '#fff', borderRadius: 12, flexShrink: 0, maxWidth: '100%', height: 'auto' }}>
      <path d={path} fill="#0b2a3a" />
    </svg>
  )
}
