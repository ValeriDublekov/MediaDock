import type {
  CatalogQuery,
  CatalogTitle,
  OscarCatalogQuery,
  OscarFilm,
  Occurrence,
  PageResponse,
  ParseLog,
  ParseLogQuery,
  ProviderSettings,
  ProviderSettingsInput,
  ScanRun,
  ScanRunQuery,
  Settings,
  SettingsInput,
  Source,
  SourceInput,
  TitleDetails,
} from './types'

const API_ROOT = '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function problemMessage(problem: unknown): string {
  if (problem && typeof problem === 'object') {
    const fields = problem as Record<string, unknown>
    if (typeof fields.detail === 'string' && fields.detail.trim()) return fields.detail
    if (fields.errors && typeof fields.errors === 'object') {
      const messages = Object.values(fields.errors as Record<string, unknown>)
        .flatMap((value) => Array.isArray(value) ? value : [value])
        .filter((value): value is string => typeof value === 'string')
      if (messages.length > 0) return messages.join(' ')
    }
    if (typeof fields.title === 'string' && fields.title.trim()) return fields.title
  }
  return 'The API returned an unexpected error.'
}

export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
  fetcher: typeof fetch = fetch,
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (typeof init.body === 'string') headers.set('Content-Type', 'application/json')

  let response: Response
  try {
    response = await fetcher(`${API_ROOT}${path}`, { ...init, headers })
  } catch {
    throw new ApiError('Could not reach the API. Check the server connection and retry.', 0)
  }

  if (!response.ok) {
    let problem: unknown
    try {
      problem = await response.json()
    } catch {
      problem = undefined
    }
    throw new ApiError(problemMessage(problem), response.status)
  }

  if (response.status === 204) return undefined as T
  try {
    return await response.json() as T
  } catch {
    throw new ApiError('The API returned an invalid response.', response.status)
  }
}

function withQuery(path: string, query: object): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      params.set(key, String(value))
    }
  }
  const serialized = params.toString()
  return serialized ? `${path}?${serialized}` : path
}

export function getCatalog(query: CatalogQuery, fetcher?: typeof fetch) {
  return requestJson<PageResponse<CatalogTitle>>(withQuery('/catalog', query), {}, fetcher)
}

export function getOscarFilms(query: OscarCatalogQuery, fetcher?: typeof fetch) {
  return requestJson<PageResponse<OscarFilm>>(withQuery('/oscars', query), {}, fetcher)
}

export function getOscarFilm(id: number, fetcher?: typeof fetch) {
  return requestJson<OscarFilm>(`/oscars/${id}`, {}, fetcher)
}

export function getTitle(id: number, fetcher?: typeof fetch) {
  return requestJson<TitleDetails>(`/titles/${id}`, {}, fetcher)
}

export function getTitleOccurrences(
  id: number,
  query: { page: number; pageSize: number },
  fetcher?: typeof fetch,
) {
  return requestJson<PageResponse<Occurrence>>(withQuery(`/titles/${id}/occurrences`, query), {}, fetcher)
}

export function getSources(fetcher?: typeof fetch) {
  return requestJson<Source[]>('/sources', {}, fetcher)
}

export function createSource(input: SourceInput, fetcher?: typeof fetch) {
  return requestJson<Source>('/sources', { method: 'POST', body: JSON.stringify(input) }, fetcher)
}

export function updateSource(id: number, input: SourceInput, fetcher?: typeof fetch) {
  return requestJson<Source>(`/sources/${id}`, { method: 'PUT', body: JSON.stringify(input) }, fetcher)
}

export function getSettings(fetcher?: typeof fetch) {
  return requestJson<Settings>('/settings', {}, fetcher)
}

export function updateSettings(input: SettingsInput, fetcher?: typeof fetch) {
  return requestJson<Settings>('/settings', { method: 'PUT', body: JSON.stringify(input) }, fetcher)
}

export function getProviderSettings(fetcher?: typeof fetch) {
  return requestJson<ProviderSettings>('/settings/providers/omdb', {}, fetcher)
}

export function updateProviderSettings(input: ProviderSettingsInput, fetcher?: typeof fetch) {
  return requestJson<ProviderSettings>(
    '/settings/providers/omdb',
    { method: 'PUT', body: JSON.stringify(input) },
    fetcher,
  )
}

export function getScanRuns(query: ScanRunQuery, fetcher?: typeof fetch) {
  return requestJson<PageResponse<ScanRun>>(withQuery('/scan-runs', query), {}, fetcher)
}

export function getParseLogs(query: ParseLogQuery, fetcher?: typeof fetch) {
  return requestJson<PageResponse<ParseLog>>(withQuery('/parse-logs', query), {}, fetcher)
}