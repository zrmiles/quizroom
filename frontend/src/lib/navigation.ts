/** Разрешаем только локальные пути после нормализации браузером. */
export function safeNext(value: string | null, origin = window.location.origin): string {
  // Управляющие символы и пробелы отвергаем намеренно: браузер вырезает их при разборе адреса.
  // eslint-disable-next-line no-control-regex
  if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\u0000-\u0020]/.test(value)) return '/quizzes'
  try {
    const url = new URL(value, origin)
    return url.origin === origin && !url.pathname.startsWith('//') ? `${url.pathname}${url.search}${url.hash}` : '/quizzes'
  } catch {
    return '/quizzes'
  }
}
