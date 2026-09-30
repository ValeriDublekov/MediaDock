import { useEffect, useState } from 'react'
import { getOscarFilm } from '../../api/client'
import type { OscarFilm } from '../../api/types'
import { EmptyState, ErrorState, LoadingState } from '../../components/Feedback'
import { formatDate, formatWords } from '../../shared/format'

interface OscarFilmDetailsDialogProps {
  filmId: number
  onClose: () => void
}

export function OscarFilmDetailsDialog({ filmId, onClose }: OscarFilmDetailsDialogProps) {
  const [film, setFilm] = useState<OscarFilm | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const winnerCount = film?.nominations.filter((nomination) => nomination.isWinner).length ?? 0

  useEffect(() => {
    let current = true
    getOscarFilm(filmId)
      .then((response) => { if (current) setFilm(response) })
      .catch((requestError: unknown) => {
        if (current) setError(requestError instanceof Error ? requestError.message : 'The Oscar film request failed.')
      })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [filmId, attempt])

  function retry() {
    setLoading(true)
    setError(null)
    setAttempt((current) => current + 1)
  }

  return (
    <div className="detail-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section aria-labelledby="oscar-film-details-heading" aria-modal="true" className="detail-dialog oscar-detail-dialog" role="dialog">
        <header className="detail-header">
          <div>
            <p className="eyebrow">ACADEMY AWARDS</p>
            <h2 id="oscar-film-details-heading">{film?.title ?? 'Oscar film'}</h2>
            {film && (
              <div className="detail-meta">
                {film.filmYear} | {film.metadataTitle} | {formatWords(film.enrichmentStatus)}
              </div>
            )}
          </div>
          <button aria-label="Close Oscar film details" className="button button-secondary" onClick={onClose} type="button">Close</button>
        </header>

        <div className="detail-body">
          {loading && <LoadingState label="Loading Oscar film details" />}
          {!loading && error && <ErrorState message={error} onRetry={retry} />}
          {!loading && !error && film && (
            <>
              <div className="oscar-details-intro">
                {film.posterUrl && (
                  <img className="oscar-detail-poster" src={film.posterUrl} alt={`Poster for ${film.title}`} />
                )}
                {film.plot && <p className="detail-description">{film.plot}</p>}
              </div>
              <dl className="detail-facts oscar-detail-facts">
                <div><dt>Award record</dt><dd>{film.nominations.length} nominations, {winnerCount} wins</dd></div>
                <div><dt>IMDb</dt><dd>{film.imdbId ?? 'Not listed'}</dd></div>
                <div><dt>IMDb rating</dt><dd>{film.imdbRating?.toFixed(1) ?? 'Not rated'}{film.imdbVotes ? ` / ${film.imdbVotes.toLocaleString()} votes` : ''}</dd></div>
                <div><dt>Metascore</dt><dd>{film.metascore ?? 'Not listed'}</dd></div>
                <div><dt>Director</dt><dd>{film.director ?? 'Not listed'}</dd></div>
                <div><dt>Runtime</dt><dd>{film.runtime ?? 'Not listed'}</dd></div>
                <div><dt>Genres</dt><dd>{film.genres.join(', ') || 'Not tagged'}</dd></div>
                <div><dt>Countries</dt><dd>{film.countries.join(', ') || 'Not tagged'}</dd></div>
                <div><dt>OMDb status</dt><dd><span className={`state-pill is-${film.enrichmentStatus.replaceAll('_', '-')}`}>{formatWords(film.enrichmentStatus)}</span></dd></div>
                <div><dt>Last attempt</dt><dd>{formatDate(film.lastEnrichmentAttemptAt)}</dd></div>
                <div><dt>Next attempt</dt><dd>{formatDate(film.nextEnrichmentAttemptAt)}</dd></div>
                <div><dt>OMDb awards</dt><dd>{film.awards ?? 'Not listed'}</dd></div>
                <div><dt>Box office</dt><dd>{film.boxOffice ?? 'Not listed'}</dd></div>
                {film.lastEnrichmentError && <div><dt>Last error</dt><dd>{film.lastEnrichmentError}</dd></div>}
              </dl>

              <section>
                <div className="section-title-row">
                  <div>
                    <h2>Nominations</h2>
                    <p>{film.nominations.length} selected-category records</p>
                  </div>
                </div>
                {film.nominations.length > 0 ? (
                  <div className="oscar-nomination-list">
                    {film.nominations.map((nomination) => (
                      <article className="oscar-nomination-row" key={nomination.id}>
                        <div className="oscar-nomination-meta">
                          <span>Ceremony {nomination.ceremony}</span>
                          <span>{formatWords(nomination.class)}</span>
                        </div>
                        <div className="oscar-nomination-copy">
                          <h3>{nomination.category}</h3>
                          {nomination.nominees && <p>{nomination.nominees}</p>}
                          {nomination.name && nomination.name !== nomination.nominees && (
                            <p className="oscar-nomination-name">{nomination.name}</p>
                          )}
                          {nomination.detail && <p className="oscar-nomination-detail">{nomination.detail}</p>}
                        </div>
                        <span className={`state-pill oscar-nomination-outcome${nomination.isWinner ? ' is-winner' : ' is-muted'}`}>
                          {nomination.isWinner ? 'Winner' : 'Nominee'}
                        </span>
                      </article>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No nominations listed" message="This film has no selected-category nomination rows." />
                )}
              </section>
            </>
          )}
        </div>
      </section>
    </div>
  )
}