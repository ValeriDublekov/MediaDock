import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getOscarFilm, getOscarFilms } from '../../api/client'
import type { OscarFilm, OscarNomination, PageResponse } from '../../api/types'
import { OscarCatalogView } from './OscarCatalogView'

vi.mock('../../api/client', () => ({
  getOscarFilm: vi.fn(),
  getOscarFilms: vi.fn(),
}))

const filmRequest = vi.mocked(getOscarFilms)
const detailsRequest = vi.mocked(getOscarFilm)

function page(items: OscarFilm[], number = 1, totalPages = 1): PageResponse<OscarFilm> {
  return { items, page: number, pageSize: 20, totalCount: items.length, totalPages }
}

const nominations: OscarNomination[] = [
  {
    id: 11,
    ceremony: 90,
    class: 'feature film',
    canonicalCategory: 'BEST PICTURE',
    category: 'Best Picture',
    name: 'The Shape of Water',
    nominees: 'Guillermo del Toro and J. Miles Dale',
    nomineeIds: '',
    detail: 'Fox Searchlight Pictures',
    isWinner: true,
  },
  {
    id: 12,
    ceremony: 90,
    class: 'feature film',
    canonicalCategory: 'DIRECTING',
    category: 'Directing',
    name: 'Guillermo del Toro',
    nominees: 'Guillermo del Toro',
    nomineeIds: '',
    detail: '',
    isWinner: false,
  },
]

const film: OscarFilm = {
  id: 7,
  titleId: 19,
  title: 'The Shape of Water',
  metadataTitle: 'The Shape of Water',
  metadataYear: 2017,
  filmYear: 2017,
  imdbId: 'tt5580390',
  enrichmentStatus: 'enriched',
  enrichmentAttemptCount: 1,
  lastEnrichmentAttemptAt: '2026-09-28T12:00:00Z',
  nextEnrichmentAttemptAt: null,
  lastEnrichmentError: null,
  mediaType: 'movie',
  imdbRating: 7.3,
  imdbVotes: 450000,
  metascore: 87,
  genres: ['Drama', 'Fantasy'],
  countries: ['USA'],
  director: 'Guillermo del Toro',
  plot: 'A woman discovers a mysterious amphibious creature.',
  posterUrl: null,
  runtime: '123 min',
  awards: '4 wins',
  boxOffice: '$63,859,435',
  nominations,
}

describe('OscarCatalogView', () => {
  beforeEach(() => {
    filmRequest.mockReset()
    detailsRequest.mockReset()
  })
  afterEach(() => cleanup())

  it('applies award filters and renders the empty state', async () => {
    filmRequest.mockResolvedValue(page([]))
    render(<OscarCatalogView />)

    fireEvent.change(screen.getByLabelText('Search films'), { target: { value: '  Oppenheimer  ' } })
    fireEvent.change(screen.getByLabelText('Year from'), { target: { value: '2022' } })
    fireEvent.change(screen.getByLabelText('Year to'), { target: { value: '2024' } })
    fireEvent.change(screen.getByLabelText('Category'), { target: { value: 'BEST PICTURE' } })
    fireEvent.change(screen.getByLabelText('Award result'), { target: { value: 'winner' } })
    fireEvent.change(screen.getByLabelText('OMDb status'), { target: { value: 'pending' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }))

    expect(await screen.findByText('No Oscar films found')).toBeTruthy()
    await waitFor(() => expect(filmRequest).toHaveBeenLastCalledWith({
      page: 1,
      pageSize: 20,
      search: 'Oppenheimer',
      yearFrom: 2022,
      yearTo: 2024,
      category: 'BEST PICTURE',
      result: 'winner',
      enrichmentStatus: 'pending',
    }))
  })

  it('opens the film details and displays all nominations and winners', async () => {
    filmRequest.mockResolvedValue(page([film]))
    detailsRequest.mockResolvedValue(film)
    render(<OscarCatalogView />)

    fireEvent.click(await screen.findByRole('button', { name: 'View The Shape of Water Oscar details' }))
    const dialog = await screen.findByRole('dialog')
    expect(detailsRequest).toHaveBeenCalledWith(film.id)
    expect(within(dialog).getByText('Guillermo del Toro and J. Miles Dale')).toBeTruthy()
    expect(within(dialog).getByText('Fox Searchlight Pictures')).toBeTruthy()
    expect(within(dialog).getByText('Winner')).toBeTruthy()
    expect(within(dialog).getByText('Nominee')).toBeTruthy()
  })

  it('requests the next page from the pagination controls', async () => {
    filmRequest.mockResolvedValue(page([film], 1, 2))
    render(<OscarCatalogView />)

    expect(await screen.findByRole('button', { name: 'View The Shape of Water Oscar details' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    await waitFor(() => expect(filmRequest).toHaveBeenLastCalledWith({ page: 2, pageSize: 20 }))
  })
})