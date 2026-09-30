import { useEffect, useState, type FormEvent } from 'react'
import { createSource, getProviderSettings, getSettings, getSources, updateProviderSettings, updateSettings, updateSource } from '../../api/client'
import type { ProviderSettings, ProviderSettingsInput, Settings, SettingsInput, Source, SourceInput } from '../../api/types'
import { EmptyState, ErrorState, LoadingState } from '../../components/Feedback'
import { formatDate } from '../../shared/format'

interface SettingsDraft {
  excludedGenres: string
  excludedCountries: string
  minMovieRating: string
  minSeriesRating: string
  minImdbVotes: string
}

interface ProviderSettingsDraft {
  omdbApiKey: string
  clearOmdbApiKey: boolean
  omdbDailyRequestLimit: string
  oscarEnrichmentMaxFilmsPerRun: string
  oscarEnrichmentMaxRequestsPerDay: string
}

const emptySource: SourceInput = { stableKey: '', name: '', feedType: 'movie', url: '', isEnabled: true }
const emptySettings: SettingsDraft = { excludedGenres: '', excludedCountries: '', minMovieRating: '0', minSeriesRating: '0', minImdbVotes: '0' }
const emptyProviderSettings: ProviderSettingsDraft = {
  omdbApiKey: '',
  clearOmdbApiKey: false,
  omdbDailyRequestLimit: '0',
  oscarEnrichmentMaxFilmsPerRun: '0',
  oscarEnrichmentMaxRequestsPerDay: '0',
}

function settingsToDraft(settings: Settings): SettingsDraft {
  return {
    excludedGenres: settings.excludedGenres.join(', '),
    excludedCountries: settings.excludedCountries.join(', '),
    minMovieRating: String(settings.minMovieRating),
    minSeriesRating: String(settings.minSeriesRating),
    minImdbVotes: String(settings.minImdbVotes),
  }
}

function providerSettingsToDraft(settings: ProviderSettings): ProviderSettingsDraft {
  return {
    ...emptyProviderSettings,
    omdbDailyRequestLimit: String(settings.omdbDailyRequestLimit),
    oscarEnrichmentMaxFilmsPerRun: String(settings.oscarEnrichmentMaxFilmsPerRun),
    oscarEnrichmentMaxRequestsPerDay: String(settings.oscarEnrichmentMaxRequestsPerDay),
  }
}

function splitValues(value: string): string[] {
  return value.split(',').map((part) => part.trim()).filter(Boolean)
}

export function SourceSettingsView() {
  const [sources, setSources] = useState<Source[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)
  const [settingsDraft, setSettingsDraft] = useState<SettingsDraft>(emptySettings)
  const [providerSettings, setProviderSettings] = useState<ProviderSettings | null>(null)
  const [providerDraft, setProviderDraft] = useState<ProviderSettingsDraft>(emptyProviderSettings)
  const [sourceDraft, setSourceDraft] = useState<SourceInput>(emptySource)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [showSourceForm, setShowSourceForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [sourceError, setSourceError] = useState<string | null>(null)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [providerError, setProviderError] = useState<string | null>(null)
  const [savingSource, setSavingSource] = useState(false)
  const [savingSettings, setSavingSettings] = useState(false)
  const [savingProvider, setSavingProvider] = useState(false)
  const [sourceSaved, setSourceSaved] = useState(false)
  const [settingsSaved, setSettingsSaved] = useState(false)
  const [providerSaved, setProviderSaved] = useState(false)

  useEffect(() => {
    let current = true
    setLoading(true)
    setLoadError(null)
    Promise.all([getSources(), getSettings(), getProviderSettings()])
      .then(([sourceList, applicationSettings, omdbSettings]) => {
        if (!current) return
        setSources(sourceList)
        setSettings(applicationSettings)
        setSettingsDraft(settingsToDraft(applicationSettings))
        setProviderSettings(omdbSettings)
        setProviderDraft(providerSettingsToDraft(omdbSettings))
      })
      .catch((requestError: unknown) => {
        if (current) setLoadError(requestError instanceof Error ? requestError.message : 'Could not load source settings.')
      })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [loadAttempt])

  function startNewSource() {
    setEditingId(null)
    setSourceDraft({ ...emptySource })
    setSourceError(null)
    setSourceSaved(false)
    setShowSourceForm(true)
  }

  function editSource(source: Source) {
    setEditingId(source.id)
    setSourceDraft({ stableKey: source.stableKey, name: source.name, feedType: source.feedType, url: source.url, isEnabled: source.isEnabled })
    setSourceError(null)
    setSourceSaved(false)
    setShowSourceForm(true)
  }

  async function saveSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSavingSource(true)
    setSourceError(null)
    setSourceSaved(false)
    try {
      const saved = editingId === null ? await createSource(sourceDraft) : await updateSource(editingId, sourceDraft)
      setSources((current) => {
        const updated = editingId === null ? [...current, saved] : current.map((source) => source.id === saved.id ? saved : source)
        return updated.sort((left, right) => left.name.localeCompare(right.name))
      })
      setShowSourceForm(false)
      setSourceDraft({ ...emptySource })
      setEditingId(null)
      setSourceSaved(true)
    } catch (requestError) {
      setSourceError(requestError instanceof Error ? requestError.message : 'Could not save this source.')
    } finally {
      setSavingSource(false)
    }
  }

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSavingSettings(true)
    setSettingsError(null)
    setSettingsSaved(false)
    const payload: SettingsInput = {
      excludedGenres: splitValues(settingsDraft.excludedGenres),
      excludedCountries: splitValues(settingsDraft.excludedCountries),
      minMovieRating: Number(settingsDraft.minMovieRating),
      minSeriesRating: Number(settingsDraft.minSeriesRating),
      minImdbVotes: Number(settingsDraft.minImdbVotes),
    }
    try {
      const saved = await updateSettings(payload)
      setSettings(saved)
      setSettingsDraft(settingsToDraft(saved))
      setSettingsSaved(true)
    } catch (requestError) {
      setSettingsError(requestError instanceof Error ? requestError.message : 'Could not save matching settings.')
    } finally {
      setSavingSettings(false)
    }
  }

  async function saveProviderSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSavingProvider(true)
    setProviderError(null)
    setProviderSaved(false)
    const payload: ProviderSettingsInput = {
      omdbApiKey: providerDraft.omdbApiKey.trim() || null,
      clearOmdbApiKey: providerDraft.clearOmdbApiKey,
      omdbDailyRequestLimit: Number(providerDraft.omdbDailyRequestLimit),
      oscarEnrichmentMaxFilmsPerRun: Number(providerDraft.oscarEnrichmentMaxFilmsPerRun),
      oscarEnrichmentMaxRequestsPerDay: Number(providerDraft.oscarEnrichmentMaxRequestsPerDay),
    }
    try {
      const saved = await updateProviderSettings(payload)
      setProviderSettings(saved)
      setProviderDraft(providerSettingsToDraft(saved))
      setProviderSaved(true)
    } catch (requestError) {
      setProviderError(requestError instanceof Error ? requestError.message : 'Could not save provider settings.')
    } finally {
      setSavingProvider(false)
    }
  }

  function updateSourceField<K extends keyof SourceInput>(key: K, value: SourceInput[K]) {
    setSourceDraft((current) => ({ ...current, [key]: value }))
  }

  function updateSettingsField<K extends keyof SettingsDraft>(key: K, value: SettingsDraft[K]) {
    setSettingsDraft((current) => ({ ...current, [key]: value }))
  }

  if (loading) return <LoadingState label="Loading source configuration" />
  if (loadError) return <ErrorState message={loadError} onRetry={() => setLoadAttempt((current) => current + 1)} />

  return (
    <section aria-label="Sources and settings">
      <div className="management-section">
        <div className="section-title-row">
          <div><h2>Feed sources</h2><p>Configured endpoints for the catalog importer</p></div>
          <button className="button" onClick={startNewSource} type="button">Add source</button>
        </div>
        {sourceSaved && <p className="form-message" role="status">Source saved.</p>}
        {sources.length === 0 ? (
          <EmptyState title="No sources configured" message="Add a feed source to begin collecting catalog entries." />
        ) : (
          <div className="source-list">
            {sources.map((source) => (
              <div className="source-row" key={source.id}>
                <div><span className="source-name">{source.name}</span><span className="source-url" title={source.url}>{source.url}</span></div>
                <span className="source-key source-kind">{source.feedType} feed</span>
                <span className={`state-pill${source.isEnabled ? '' : ' is-muted'}`}>{source.isEnabled ? 'Enabled' : 'Disabled'}</span>
                <button aria-label={`Edit ${source.name}`} className="text-button source-action" onClick={() => editSource(source)} type="button">Edit</button>
              </div>
            ))}
          </div>
        )}

        {showSourceForm && (
          <form className="source-form" onSubmit={saveSource}>
            <div className="section-title-row"><div><h2>{editingId === null ? 'New source' : 'Edit source'}</h2><p>Source URLs are validated by the API before saving.</p></div></div>
            <div className="form-grid">
              <div className="field"><label htmlFor="source-name">Name</label><input id="source-name" maxLength={200} onChange={(event) => updateSourceField('name', event.target.value)} required value={sourceDraft.name} /></div>
              <div className="field"><label htmlFor="source-key">Stable key</label><input id="source-key" maxLength={100} onChange={(event) => updateSourceField('stableKey', event.target.value)} pattern="[a-z0-9][a-z0-9._-]{0,99}" required value={sourceDraft.stableKey} /></div>
              <div className="field"><label htmlFor="source-feed-type">Feed type</label><select id="source-feed-type" onChange={(event) => updateSourceField('feedType', event.target.value as 'movie' | 'series')} value={sourceDraft.feedType}><option value="movie">Movie</option><option value="series">Series</option></select></div>
              <div className="field"><label htmlFor="source-url">Feed URL</label><input id="source-url" maxLength={2048} onChange={(event) => updateSourceField('url', event.target.value)} required type="url" value={sourceDraft.url} /></div>
            </div>
            <label className="checkbox-field"><input checked={sourceDraft.isEnabled} onChange={(event) => updateSourceField('isEnabled', event.target.checked)} type="checkbox" />Enabled for ingestion</label>
            {sourceError && <p className="form-error" role="alert">{sourceError}</p>}
            <div className="form-actions">
              <button className="button" disabled={savingSource} type="submit">{savingSource ? 'Saving...' : 'Save source'}</button>
              <button className="button button-secondary" onClick={() => setShowSourceForm(false)} type="button">Cancel</button>
            </div>
          </form>
        )}
      </div>

      <div className="management-grid">
        <section aria-labelledby="matching-settings-heading">
          <h2 id="matching-settings-heading">Matching settings</h2>
          <p className="section-caption">Thresholds and exclusions applied to feed matches.</p>
          <form className="settings-form" onSubmit={saveSettings}>
            <div className="field"><label htmlFor="excluded-genres">Excluded genres</label><textarea id="excluded-genres" onChange={(event) => updateSettingsField('excludedGenres', event.target.value)} placeholder="Comma-separated values" value={settingsDraft.excludedGenres} /></div>
            <div className="field"><label htmlFor="excluded-countries">Excluded countries</label><textarea id="excluded-countries" onChange={(event) => updateSettingsField('excludedCountries', event.target.value)} placeholder="Comma-separated values" value={settingsDraft.excludedCountries} /></div>
            <div className="form-grid">
              <div className="field"><label htmlFor="min-movie-rating">Minimum movie rating</label><input id="min-movie-rating" max="10" min="0" onChange={(event) => updateSettingsField('minMovieRating', event.target.value)} required step="0.1" type="number" value={settingsDraft.minMovieRating} /></div>
              <div className="field"><label htmlFor="min-series-rating">Minimum series rating</label><input id="min-series-rating" max="10" min="0" onChange={(event) => updateSettingsField('minSeriesRating', event.target.value)} required step="0.1" type="number" value={settingsDraft.minSeriesRating} /></div>
            </div>
            <div className="field"><label htmlFor="min-imdb-votes">Minimum IMDb votes</label><input id="min-imdb-votes" max="1000000000" min="0" onChange={(event) => updateSettingsField('minImdbVotes', event.target.value)} required type="number" value={settingsDraft.minImdbVotes} /></div>
            {settings?.updatedAt && <p className="section-caption">Last updated {formatDate(settings.updatedAt)}</p>}
            {settingsError && <p className="form-error" role="alert">{settingsError}</p>}
            {settingsSaved && <p className="form-message" role="status">Matching settings saved.</p>}
            <div className="form-actions"><button className="button" disabled={savingSettings} type="submit">{savingSettings ? 'Saving...' : 'Save settings'}</button></div>
          </form>
        </section>

        <section aria-labelledby="provider-settings-heading">
          <h2 id="provider-settings-heading">OMDb provider</h2>
          <p className="section-caption">Credentials and request limits used by the one-shot Worker.</p>
          <form className="settings-form" onSubmit={saveProviderSettings}>
            <div className="field">
              <label htmlFor="omdb-api-key">OMDb API key</label>
              <input
                autoComplete="new-password"
                id="omdb-api-key"
                maxLength={512}
                onChange={(event) => setProviderDraft((current) => ({
                  ...current,
                  omdbApiKey: event.target.value,
                  clearOmdbApiKey: false,
                }))}
                placeholder={providerSettings?.omdbApiKeyConfigured ? 'Leave blank to keep saved key' : 'Enter API key'}
                type="password"
                value={providerDraft.omdbApiKey}
              />
              {providerSettings?.omdbApiKeyConfigured && <span className="state-pill is-enriched">Key configured</span>}
            </div>
            <label className="checkbox-field">
              <input
                checked={providerDraft.clearOmdbApiKey}
                disabled={!providerSettings?.omdbApiKeyConfigured}
                onChange={(event) => setProviderDraft((current) => ({
                  ...current,
                  omdbApiKey: '',
                  clearOmdbApiKey: event.target.checked,
                }))}
                type="checkbox"
              />
              Clear saved key
            </label>
            <div className="field">
              <label htmlFor="omdb-daily-limit">Shared daily HTTP request limit</label>
              <input id="omdb-daily-limit" min="0" onChange={(event) => setProviderDraft((current) => ({ ...current, omdbDailyRequestLimit: event.target.value }))} required type="number" value={providerDraft.omdbDailyRequestLimit} />
            </div>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="oscar-max-films">Oscar films per run</label>
                <input id="oscar-max-films" max="100000" min="0" onChange={(event) => setProviderDraft((current) => ({ ...current, oscarEnrichmentMaxFilmsPerRun: event.target.value }))} required type="number" value={providerDraft.oscarEnrichmentMaxFilmsPerRun} />
              </div>
              <div className="field">
                <label htmlFor="oscar-daily-limit">Oscar daily HTTP limit</label>
                <input id="oscar-daily-limit" min="0" onChange={(event) => setProviderDraft((current) => ({ ...current, oscarEnrichmentMaxRequestsPerDay: event.target.value }))} required type="number" value={providerDraft.oscarEnrichmentMaxRequestsPerDay} />
              </div>
            </div>
            <p className="section-caption">Set a positive shared limit matching the OMDb key's confirmed quota. Oscar limits are additional caps, not reserved capacity; RSS runs first. Set Oscar films per run to 0 to disable enrichment.</p>
            {providerSettings?.updatedAt && <p className="section-caption">Last updated {formatDate(providerSettings.updatedAt)}</p>}
            {providerError && <p className="form-error" role="alert">{providerError}</p>}
            {providerSaved && <p className="form-message" role="status">Provider settings saved.</p>}
            <div className="form-actions"><button className="button" disabled={savingProvider} type="submit">{savingProvider ? 'Saving...' : 'Save provider settings'}</button></div>
          </form>
        </section>
      </div>
      <p className="trust-note">The API key is stored in the local database and never returned by the API. Settings writes are unauthenticated and use the local HTTP connection, so keep MediaDock on a trusted LAN and protect database backups.</p>
    </section>
  )
}