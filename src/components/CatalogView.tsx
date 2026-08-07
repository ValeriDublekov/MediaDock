import React from 'react';
import { CatalogRepository, Title } from '../domain/catalog';
import { useCatalog } from '../application/useCatalog';
import { Loader2, AlertCircle, RefreshCw, Film } from 'lucide-react';

interface CatalogViewProps {
  repository?: CatalogRepository;
  pageSize?: number;
}

export const CatalogView: React.FC<CatalogViewProps> = ({ repository, pageSize = 10 }) => {
  const {
    titles,
    isLoading,
    isLoadingMore,
    error,
    hasMore,
    isEmpty,
    loadNextPage,
    retry,
  } = useCatalog({ repository, pageSize });

  if (isLoading) {
    return (
      <div
        data-testid="catalog-loading"
        className="flex flex-col items-center justify-center py-16 text-neutral-500"
      >
        <Loader2 className="w-8 h-8 animate-spin mb-3 text-neutral-400" />
        <p className="text-sm font-medium">Loading catalog...</p>
      </div>
    );
  }

  if (error && titles.length === 0) {
    return (
      <div
        data-testid="catalog-error"
        className="flex flex-col items-center justify-center py-16 text-center px-4"
      >
        <div className="w-12 h-12 rounded-full bg-red-50 text-red-600 flex items-center justify-center mb-4">
          <AlertCircle className="w-6 h-6" />
        </div>
        <h3 className="text-base font-semibold text-neutral-900 mb-1">Failed to load catalog</h3>
        <p className="text-sm text-neutral-500 max-w-md mb-6">{error.message}</p>
        <button
          onClick={retry}
          data-testid="catalog-retry-button"
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-neutral-700 bg-white border border-neutral-300 rounded-lg shadow-xs hover:bg-neutral-50 transition-colors cursor-pointer"
        >
          <RefreshCw className="w-4 h-4" />
          Retry
        </button>
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div
        data-testid="catalog-empty"
        className="flex flex-col items-center justify-center py-16 text-center px-4"
      >
        <div className="w-12 h-12 rounded-full bg-neutral-100 text-neutral-400 flex items-center justify-center mb-4">
          <Film className="w-6 h-6" />
        </div>
        <h3 className="text-base font-semibold text-neutral-900 mb-1">Catalog is empty</h3>
        <p className="text-sm text-neutral-500 max-w-md">No media titles are currently available in the catalog.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div data-testid="catalog-list" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {titles.map((item: Title) => (
          <div
            key={item.id}
            data-testid="title-card"
            className="bg-white border border-neutral-200 rounded-xl p-4 shadow-xs hover:border-neutral-300 transition-all flex flex-col justify-between"
          >
            <div>
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3 className="font-semibold text-neutral-900 text-base line-clamp-1" title={item.title}>
                  {item.title}
                </h3>
                {item.year && (
                  <span className="text-xs font-medium px-2 py-0.5 rounded-md bg-neutral-100 text-neutral-600 whitespace-nowrap">
                    {item.year}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 text-xs text-neutral-500 mb-3">
                <span className="capitalize font-medium text-neutral-700 px-2 py-0.5 rounded bg-neutral-50 border border-neutral-100">
                  {item.mediaType}
                </span>
                {item.imdbRating !== null && item.imdbRating !== undefined && (
                  <span className="font-medium text-amber-600">★ {item.imdbRating}</span>
                )}
                {item.genres && item.genres.length > 0 && (
                  <span className="truncate">{item.genres.join(', ')}</span>
                )}
              </div>
              {item.plot && (
                <p className="text-xs text-neutral-600 line-clamp-2 mb-3">{item.plot}</p>
              )}
            </div>
            <div className="pt-2 border-t border-neutral-100 text-[11px] text-neutral-400 flex justify-between items-center">
              <span>Last seen: {new Date(item.lastSeenAt).toLocaleDateString()}</span>
              <span className="font-mono">{item.id}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Error state during loadNextPage */}
      {error && titles.length > 0 && (
        <div data-testid="catalog-error" className="flex items-center justify-between p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          <span>Failed to load next page: {error.message}</span>
          <button
            onClick={retry}
            data-testid="catalog-retry-button"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-700 bg-white border border-red-300 rounded-md hover:bg-red-100 transition-colors cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Retry
          </button>
        </div>
      )}

      {/* Pagination Footer */}
      <div className="flex justify-center pt-4">
        {hasMore ? (
          <button
            onClick={loadNextPage}
            disabled={isLoadingMore}
            data-testid="catalog-load-more-button"
            className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-neutral-700 bg-white border border-neutral-300 rounded-lg shadow-xs hover:bg-neutral-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
          >
            {isLoadingMore ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin text-neutral-500" />
                <span data-testid="catalog-loading-more">Loading more...</span>
              </>
            ) : (
              'Load More'
            )}
          </button>
        ) : (
          <div data-testid="catalog-end-of-results" className="text-xs text-neutral-400 py-2">
            End of catalog
          </div>
        )}
      </div>
    </div>
  );
};
