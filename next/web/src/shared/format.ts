export function formatDate(value: string | null | undefined): string {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

export function formatWords(value: string | null | undefined): string {
  if (!value) return 'Not set'
  return value.replaceAll('_', ' ')
}