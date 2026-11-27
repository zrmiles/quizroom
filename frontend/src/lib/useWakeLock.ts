import { useEffect } from 'react'

/**
 * Не даёт экрану погаснуть, пока идёт игра: погасший телефон рвёт соединение,
 * а проектор с экраном ведущего засыпает посреди вопроса.
 * Браузер снимает блокировку, когда вкладка скрыта, — при возвращении берём её снова.
 */
export function useWakeLock(active: boolean): void {
  useEffect(() => {
    const wakeLock = (navigator as Navigator & { wakeLock?: { request: (t: 'screen') => Promise<{ release: () => Promise<void> }> } }).wakeLock
    if (!active || !wakeLock) return
    let lock: { release: () => Promise<void> } | null = null
    let stopped = false
    const acquire = () => {
      if (document.visibilityState !== 'visible') return
      wakeLock.request('screen')
        .then((l) => { if (stopped) void l.release(); else lock = l })
        .catch(() => { /* нет разрешения или режим энергосбережения — игра работает и так */ })
    }
    acquire()
    document.addEventListener('visibilitychange', acquire)
    return () => {
      stopped = true
      document.removeEventListener('visibilitychange', acquire)
      void lock?.release().catch(() => {})
    }
  }, [active])
}
