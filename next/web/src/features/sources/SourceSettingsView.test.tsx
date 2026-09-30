import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createSource,
  getProviderSettings,
  getSettings,
  getSources,
  updateProviderSettings,
  updateSettings,
  updateSource,
} from '../../api/client'
import type { ProviderSettings, Settings } from '../../api/types'
import { SourceSettingsView } from './SourceSettingsView'

vi.mock('../../api/client', () => ({
  createSource: vi.fn(),
  getProviderSettings: vi.fn(),
  getSettings: vi.fn(),
  getSources: vi.fn(),
  updateProviderSettings: vi.fn(),
  updateSettings: vi.fn(),
  updateSource: vi.fn(),
}))

const providerSettings: ProviderSettings = {
  omdbApiKeyConfigured: true,
  omdbDailyRequestLimit: 25,
  oscarEnrichmentMaxFilmsPerRun: 0,
  oscarEnrichmentMaxRequestsPerDay: 0,
  updatedAt: null,
}

describe('SourceSettingsView', () => {
  beforeEach(() => {
    vi.mocked(createSource).mockReset()
    vi.mocked(getProviderSettings).mockReset().mockResolvedValue(providerSettings)
    vi.mocked(getSettings).mockReset().mockResolvedValue({
      excludedGenres: [],
      excludedCountries: [],
      minMovieRating: 0,
      minSeriesRating: 0,
      minImdbVotes: 0,
      updatedAt: null,
    } satisfies Settings)
    vi.mocked(getSources).mockReset().mockResolvedValue([])
    vi.mocked(updateProviderSettings).mockReset().mockResolvedValue(providerSettings)
    vi.mocked(updateSettings).mockReset()
    vi.mocked(updateSource).mockReset()
  })

  afterEach(() => cleanup())

  it('keeps the saved key write-only and clears a replacement after saving', async () => {
    render(<SourceSettingsView />)

    const keyInput = await screen.findByLabelText('OMDb API key') as HTMLInputElement
    expect(keyInput.type).toBe('password')
    expect(keyInput.value).toBe('')
    expect(screen.getByText('Key configured')).toBeTruthy()

    fireEvent.change(keyInput, { target: { value: 'replacement-test-key' } })
    fireEvent.change(screen.getByLabelText('Shared daily HTTP request limit'), { target: { value: '25' } })
    fireEvent.change(screen.getByLabelText('Oscar films per run'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('Oscar daily HTTP limit'), { target: { value: '8' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save provider settings' }))

    await waitFor(() => expect(updateProviderSettings).toHaveBeenCalledWith({
      omdbApiKey: 'replacement-test-key',
      clearOmdbApiKey: false,
      omdbDailyRequestLimit: 25,
      oscarEnrichmentMaxFilmsPerRun: 10,
      oscarEnrichmentMaxRequestsPerDay: 8,
    }))
    expect(await screen.findByText('Provider settings saved.')).toBeTruthy()
    expect(keyInput.value).toBe('')
  })
})