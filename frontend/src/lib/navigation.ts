/** Разрешаем только локальные пути после нормализации браузером. */
export function safeNext(value: string | null, origin = window.location.origin): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\u0000-\u0020]/.test(value)) return '/quizzes'
  try {
    const url = new URL(value, origin)
    return url.origin === origin && !url.pathname.startsWith('//') ? `${url.pathname}${url.search}${url.hash}` : '/quizzes'
  } catch {
    return '/quizzes'
  }
}
