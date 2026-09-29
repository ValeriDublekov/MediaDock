import type { PageResponse } from '../api/types'

interface PaginationProps {
  page: Pick<PageResponse<unknown>, 'page' | 'totalCount' | 'totalPages'>
  onPageChange: (page: number) => void
}

export function Pagination({ page, onPageChange }: PaginationProps) {
  const lastPage = Math.max(page.totalPages, 1)

  return (
    <div className="pagination">
      <span>
        {page.totalCount.toLocaleString()} {page.totalCount === 1 ? 'title' : 'records'}
        <span aria-hidden="true"> | </span>
        Page {page.page} of {lastPage}
      </span>
      <div className="pagination-actions">
        <button aria-label="Previous page" className="button button-secondary" disabled={page.page <= 1} onClick={() => onPageChange(page.page - 1)} type="button">Previous</button>
        <button aria-label="Next page" className="button button-secondary" disabled={page.totalPages === 0 || page.page >= page.totalPages} onClick={() => onPageChange(page.page + 1)} type="button">Next</button>
      </div>
    </div>
  )
}