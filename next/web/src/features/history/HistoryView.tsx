import { useEffect, useState, type FormEvent } from 'react'
import { getParseLogs, getScanRuns } from '../../api/client'
import type { PageResponse, ParseLog, ScanRun } from '../../api/types'
import { EmptyState, ErrorState, LoadingState } from '../../components/Feedback'
import { Pagination } from '../../components/Pagination'
import { formatDate, formatWords } from '../../shared/format'

type HistoryTab = 'scans' | 'parses'

export function HistoryView() {
  const [tab, setTab] = useState<HistoryTab>('scans')
  const [page, setPage] = useState(1)
  const [scanStatus, setScanStatus] = useState('')
  const [scanTrigger, setScanTrigger] = useState('')
  const [retryState, setRetryState] = useState('')
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')
  const [scanResult, setScanResult] = useState<PageResponse<ScanRun> | null>(null)
  const [parseResult, setParseResult] = useState<PageResponse<ParseLog> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let current = true
    setLoading(true)
    setError(null)
    const request = tab === 'scans'
      ? getScanRuns({
        page,
        pageSize: 20,
        ...(scanStatus ? { status: scanStatus as ScanRun['status'] } : {}),
        ...(scanTrigger ? { trigger: scanTrigger as ScanRun['trigger'] } : {}),
      })
      : getParseLogs({
        page,
        pageSize: 20,
        ...(retryState ? { retryState: retryState as 'retryable' | 'terminal' | 'resolved' } : {}),
        ...(search ? { search } : {}),
      })

    request
      .then((result) => {
        if (!current) return
        if (tab === 'scans') setScanResult(result as PageResponse<ScanRun>)
        else setParseResult(result as PageResponse<ParseLog>)
      })
      .catch((requestError: unknown) => {
        if (current) setError(requestError instanceof Error ? requestError.message : 'Could not load operation history.')
      })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [tab, page, scanStatus, scanTrigger, retryState, search, attempt])

  function changeTab(nextTab: HistoryTab) {
    setTab(nextTab)
    setPage(1)
  }

  function applySearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPage(1)
    setSearch(searchDraft.trim())
  }

  const activeResult = tab === 'scans' ? scanResult : parseResult

  return (
    <section aria-label="Operation history">
      <div className="history-toolbar">
        <div aria-label="History type" className="segment-control" role="group">
          <button aria-pressed={tab === 'scans'} onClick={() => changeTab('scans')} type="button">Scan runs</button>
          <button aria-pressed={tab === 'parses'} onClick={() => changeTab('parses')} type="button">Parse log</button>
        </div>
        {tab === 'scans' ? (
          <div className="history-filters">
            <div className="field"><label htmlFor="scan-status-filter">Status</label><select id="scan-status-filter" onChange={(event) => { setPage(1); setScanStatus(event.target.value) }} value={scanStatus}><option value="">All statuses</option><option value="running">Running</option><option value="succeeded">Succeeded</option><option value="partial">Partial</option><option value="failed">Failed</option></select></div>
            <div className="field"><label htmlFor="scan-trigger-filter">Trigger</label><select id="scan-trigger-filter" onChange={(event) => { setPage(1); setScanTrigger(event.target.value) }} value={scanTrigger}><option value="">All triggers</option><option value="schedule">Schedule</option><option value="manual">Manual</option><option value="local">Local</option></select></div>
          </div>
        ) : (
          <form className="history-filters" onSubmit={applySearch}>
            <div className="field"><label htmlFor="parse-retry-filter">Retry state</label><select id="parse-retry-filter" onChange={(event) => { setPage(1); setRetryState(event.target.value) }} value={retryState}><option value="">All states</option><option value="retryable">Retryable</option><option value="terminal">Terminal</option><option value="resolved">Resolved</option></select></div>
            <div className="field field-search"><label htmlFor="parse-search">Search entries</label><input id="parse-search" onChange={(event) => setSearchDraft(event.target.value)} placeholder="Title or feed" value={searchDraft} /></div>
            <button className="button" type="submit">Search</button>
          </form>
        )}
      </div>

      {loading && <LoadingState label={tab === 'scans' ? 'Loading scan history' : 'Loading parse history'} />}
      {!loading && error && <ErrorState message={error} onRetry={() => setAttempt((current) => current + 1)} />}
      {!loading && !error && activeResult && activeResult.items.length === 0 && (
        <EmptyState title={tab === 'scans' ? 'No scan runs found' : 'No parse entries found'} message="History will appear here after the worker processes configured feeds." />
      )}
      {!loading && !error && activeResult && activeResult.items.length > 0 && (
        <>
          {tab === 'scans' && <ScanRunTable items={scanResult?.items ?? []} />}
          {tab === 'parses' && <ParseLogTable items={parseResult?.items ?? []} />}
          <Pagination onPageChange={setPage} page={activeResult} />
        </>
      )}
    </section>
  )
}

function ScanRunTable({ items }: { items: ScanRun[] }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead><tr><th>STARTED</th><th>STATUS</th><th>TRIGGER</th><th>FEEDS</th><th>ENTRIES</th><th>ADDED</th><th>ISSUES</th></tr></thead>
        <tbody>{items.map((run) => (
          <tr key={run.id}>
            <td>{formatDate(run.startedAt)}<span className="subtle-line">Finished {formatDate(run.finishedAt)}</span></td>
            <td><span className={`state-pill${run.status === 'failed' || run.status === 'partial' ? ' is-muted' : ''}`}>{formatWords(run.status)}</span></td>
            <td>{formatWords(run.trigger)}</td><td>{run.feedsProcessed}</td><td>{run.entriesSeen}</td>
            <td>{run.titlesCreated} titles<span className="subtle-line">{run.occurrencesCreated} observations</span></td>
            <td>{run.errorCount ? run.errorSummary.join('; ') || `${run.errorCount} issues` : 'None'}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}

function ParseLogTable({ items }: { items: ParseLog[] }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead><tr><th>RAW TITLE</th><th>FEED</th><th>PARSE</th><th>DECISION</th><th>RETRY</th><th>PROCESSED</th></tr></thead>
        <tbody>{items.map((entry) => (
          <tr key={entry.id}>
            <td>{entry.rawTitle}<span className="subtle-line">{entry.parsedTitle ?? 'No normalized title'}{entry.parsedYear ? ` | ${entry.parsedYear}` : ''}</span></td>
            <td>{entry.sourceName ?? entry.feedName}<span className="subtle-line">{entry.feedType ?? 'Unknown feed type'}</span></td>
            <td><span className={`state-pill${entry.parsedSuccessfully ? '' : ' is-muted'}`}>{entry.parsedSuccessfully ? 'Parsed' : 'Rejected'}</span></td>
            <td>{entry.decision ?? entry.ignoreReason ?? entry.errorMessage ?? (entry.ignored ? 'Ignored' : 'No decision')}</td>
            <td>{formatWords(entry.retryState)}<span className="subtle-line">{entry.attemptCount} attempts</span></td>
            <td>{formatDate(entry.processedAt)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}