import { useEffect, useState } from 'react'
import { getTitle, getTitleOccurrences } from '../../api/client'
import type { Occurrence, PageResponse, TitleDetails } from '../../api/types'
import { EmptyState, ErrorState, LoadingState } from '../../components/Feedback'
import { formatDate, formatWords } from '../../shared/format'

interface TitleDetailsDialogProps {
  titleId: number
  onClose: () => void
}

export function TitleDetailsDialog({ titleId, onClose }: TitleDetailsDialogProps) {
  const [title, setTitle] = useState<TitleDetails | null>(null)
  const [occurrences, setOccurrences] = useState<PageResponse<Occurrence> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let current = true
    setLoading(true)
    setError(null)
    Promise.all([getTitle(titleId), getTitleOccurrences(titleId, { page: 1, pageSize: 5 })])
      .then(([details, page]) => {
        if (!current) return
        setTitle(details)
        setOccurrences(page)
      })
      .catch((requestError: unknown) => {
        if (current) setError(requestError instanceof Error ? requestError.message : 'The title request failed.')
      })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [titleId, attempt])

  return (
    <div className="detail-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section aria-labelledby="title-details-heading" aria-modal="true" className="detail-dialog" role="dialog">
        <header className="detail-header">
          <div>
            <p className="eyebrow">TITLE DETAILS</p>
            <h2 id="title-details-heading">{title?.title ?? 'Catalog title'}</h2>
            {title && <div className="detail-meta">{title.year ?? 'Year unknown'} | {formatWords(title.mediaType)} | {title.occurrenceCount} observations</div>}
          </div>
          <button aria-label="Close title details" className="button button-secondary" onClick={onClose} type="button">Close</button>
        </header>

        <div className="detail-body">
          {loading && <LoadingState label="Loading title details" />}
          {!loading && error && <ErrorState message={error} onRetry={() => setAttempt((current) => current + 1)} />}
          {!loading && !error && title && (
            <>
              {title.plot && <p className="detail-description">{title.plot}</p>}
              <dl className="detail-facts">
                <div><dt>Rating</dt><dd>{title.imdbRating?.toFixed(1) ?? 'Not rated'}{title.imdbVotes ? ` / ${title.imdbVotes.toLocaleString()} votes` : ''}</dd></div>
                <div><dt>Director</dt><dd>{title.director ?? 'Not listed'}</dd></div>
                <div><dt>Runtime</dt><dd>{title.runtime ?? 'Not listed'}</dd></div>
                <div><dt>Genres</dt><dd>{title.genres.join(', ') || 'Not tagged'}</dd></div>
                <div><dt>Countries</dt><dd>{title.countries.join(', ') || 'Not tagged'}</dd></div>
                <div><dt>First seen</dt><dd>{formatDate(title.firstSeenAt)}</dd></div>
              </dl>
              <div>
                <div className="section-title-row"><div><h2>Feed observations</h2><p>Most recently seen occurrences</p></div></div>
                {occurrences?.items.length ? (
                  <div className="occurrence-list">{occurrences.items.map((item) => <OccurrenceRow item={item} key={item.id} />)}</div>
                ) : (
                  <EmptyState title="No observations recorded" message="This title has no linked feed occurrences yet." />
                )}
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  )
}

function OccurrenceRow({ item }: { item: Occurrence }) {
  return (
    <div className="occurrence-row">
      <div>
        <strong>{item.sourceName} | {item.sourceFeedName}</strong>
        <span>{item.rawTitle}</span>
        <span>Last seen {formatDate(item.lastSeenAt)}</span>
      </div>
      <a href={item.torrentUrl} rel="noreferrer" target="_blank">Open source</a>
    </div>
  )
}