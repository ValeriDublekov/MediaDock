import { describe, expect, it } from 'vitest'
import { ApiError, getCatalog, requestJson } from './client'
import type { CatalogTitle, PageResponse } from './types'

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