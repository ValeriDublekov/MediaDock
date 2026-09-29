interface LoadingStateProps {
  label?: string
}

export function LoadingState({ label = 'Loading data' }: LoadingStateProps) {
  return (
    <div className="feedback" role="status" aria-live="polite">
      <span className="loading-spinner" aria-hidden="true" />
      <span className="loading-line">{label}</span>
    </div>
  )
}

interface ErrorStateProps {
  message: string
  onRetry: () => void
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="feedback feedback-error" role="alert">
      <span className="feedback-symbol" aria-hidden="true">!</span>
      <div className="feedback-copy">
        <strong>Could not load this view</strong>
        <p>{message}</p>
      </div>
      <button className="button button-secondary" onClick={onRetry} type="button">Retry</button>
    </div>
  )
}

interface EmptyStateProps {
  title: string
  message: string
}

export function EmptyState({ title, message }: EmptyStateProps) {
  return (
    <div className="feedback" role="status">
      <span className="feedback-symbol" aria-hidden="true">-</span>
      <div className="feedback-copy">
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
    </div>
  )
}