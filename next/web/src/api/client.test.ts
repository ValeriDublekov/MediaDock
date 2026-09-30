import { describe, expect, it } from 'vitest'
import { ApiError, getCatalog, getOscarFilm, getOscarFilms, getProviderSettings, requestJson, updateProviderSettings } from './client'
import type { CatalogTitle, OscarFilm, PageResponse, ProviderSettings, ProviderSettingsInput } from './types'

function response(status: number, value: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => value } as Response
}

function fetchStub(result: Response | Error) {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = []
  const fetcher: typeof fetch = async (input, init) => {
    calls.push({ input, init })
    if (result instanceof Error) throw result
    return result
  }
  return { fetcher, calls }
}

describe('typed API client', () => {
  it('serializes pagination and catalog filters into the Step 6 query contract', async () => {
    const page: PageResponse<CatalogTitle> = { items: [], page: 2, pageSize: 20, totalCount: 0, totalPages: 0 }
    const stub = fetchStub(response(200, page))

    await getCatalog({ page: 2, pageSize: 20, search: 'quiet river', mediaType: 'series', yearFrom: 1998, genre: 'drama' }, stub.fetcher)

    const requestUrl = new URL(String(stub.calls[0]?.input), 'http://localhost')
    expect(requestUrl.pathname).toBe('/api/catalog')
    expect(requestUrl.searchParams.get('page')).toBe('2')
    expect(requestUrl.searchParams.get('pageSize')).toBe('20')
    expect(requestUrl.searchParams.get('search')).toBe('quiet river')
    expect(requestUrl.searchParams.get('mediaType')).toBe('series')
    expect(requestUrl.searchParams.get('yearFrom')).toBe('1998')
    expect(requestUrl.searchParams.get('genre')).toBe('drama')
  })

  it('serializes Oscar filters and requests one film with its nomination details', async () => {
    const page: PageResponse<OscarFilm> = { items: [], page: 2, pageSize: 20, totalCount: 0, totalPages: 0 }
    const stub = fetchStub(response(200, page))

    await getOscarFilms({
      page: 2,
      pageSize: 20,
      search: 'Oppenheimer',
      yearFrom: 2022,
      yearTo: 2024,
      category: 'BEST PICTURE',
      result: 'winner',
      enrichmentStatus: 'pending',
    }, stub.fetcher)
    await getOscarFilm(42, stub.fetcher)

    const listUrl = new URL(String(stub.calls[0]?.input), 'http://localhost')
    expect(listUrl.pathname).toBe('/api/oscars')
    expect(listUrl.searchParams.get('yearFrom')).toBe('2022')
    expect(listUrl.searchParams.get('yearTo')).toBe('2024')
    expect(listUrl.searchParams.get('category')).toBe('BEST PICTURE')
    expect(listUrl.searchParams.get('result')).toBe('winner')
    expect(listUrl.searchParams.get('enrichmentStatus')).toBe('pending')
    expect(String(stub.calls[1]?.input)).toBe('/api/oscars/42')
  })

  it('loads provider settings and sends a write-only key update', async () => {
    const providerSettings: ProviderSettings = {
      omdbApiKeyConfigured: true,
      omdbDailyRequestLimit: 25,
      oscarEnrichmentMaxFilmsPerRun: 10,
      oscarEnrichmentMaxRequestsPerDay: 8,
      updatedAt: null,
    }
    const input: ProviderSettingsInput = {
      omdbApiKey: 'new-key-value',
      clearOmdbApiKey: false,
      omdbDailyRequestLimit: 25,
      oscarEnrichmentMaxFilmsPerRun: 10,
      oscarEnrichmentMaxRequestsPerDay: 8,
    }
    const stub = fetchStub(response(200, providerSettings))

    await getProviderSettings(stub.fetcher)
    await updateProviderSettings(input, stub.fetcher)

    expect(String(stub.calls[0]?.input)).toBe('/api/settings/providers/omdb')
    expect(stub.calls[1]?.init?.method).toBe('PUT')
    expect(JSON.parse(String(stub.calls[1]?.init?.body))).toEqual(input)
  })

  it('surfaces ProblemDetails validation errors with their HTTP status', async () => {
    const stub = fetchStub(response(400, {
      title: 'One or more validation errors occurred.',
      errors: { PageSize: ['The field PageSize must be between 1 and 100.'] },
    }))

    await expect(requestJson('/catalog?pageSize=500', {}, stub.fetcher)).rejects.toMatchObject({
      name: 'ApiError',
      status: 400,
      message: 'The field PageSize must be between 1 and 100.',
    })
  })

  it('reports a retryable connection error when the API is unavailable', async () => {
    const stub = fetchStub(new TypeError('offline'))

    await expect(requestJson('/catalog', {}, stub.fetcher)).rejects.toMatchObject({
      name: 'ApiError',
      status: 0,
      message: 'Could not reach the API. Check the server connection and retry.',
    } satisfies Partial<ApiError>)
  })
})