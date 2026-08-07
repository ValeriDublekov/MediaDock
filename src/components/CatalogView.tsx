import React, { useState, useMemo } from 'react';
import { CatalogRepository, Title } from '../domain/catalog';
import { useCatalog } from '../application/useCatalog';
import { firestoreCatalogAdapter } from '../adapters/firestoreCatalogAdapter';
import { CatalogFilterBar } from './CatalogFilterBar';
import { TitleCard } from './TitleCard';
import { CatalogSkeleton } from './CatalogSkeleton';
import {
  CatalogFilterState,
  DEFAULT_FILTER_STATE,
  filterAndSortTitles,
} from '../domain/catalogFilter';
import { AlertCircle, RefreshCw, Film, Loader2, FilterX, RotateCcw } from 'lucide-react';

interface CatalogViewProps {
  repository?: CatalogRepository;
  pageSize?: number;
}

export const CatalogView: React.FC<CatalogViewProps> = ({ repository = firestoreCatalogAdapter, pageSize = 10 }) => {
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

  const [filterState, setFilterState] = useState<CatalogFilterState>(DEFAULT_FILTER_STATE);

  const filteredTitles = useMemo(() => {
    return filterAndSortTitles(titles, filterState);
  }, [titles, filterState]);

  if (isLoading) {
    return <CatalogSkeleton count={pageSize} />;
  }

  if (error && titles.length === 0) {
    return (
      <div
        data-testid="catalog-error"
        className="flex flex-col items-center justify-center py-16 text-center px-4 bg-neutral-900 border border-neutral-800 rounded-xl"
      >
        <div className="w-12 h-12 rounded-full bg-red-950/50 border border-red-800/60 text-red-400 flex items-center justify-center mb-4">
          <AlertCircle className="w-6 h-6" />
        </div>
        <h3 className="text-base font-semibold text-neutral-100 mb-1">Failed to load catalog</h3>
        <p className="text-sm text-neutral-400 max-w-md mb-6">{error.message}</p>
        <button
          onClick={retry}
          data-testid="catalog-retry-button"
          className="inline-flex items-center gap-2 min-h-[44px] px-5 py-2.5 text-sm font-medium text-neutral-200 bg-neutral-800 border border-neutral-700 rounded-lg hover:bg-neutral-700 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer"
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
        className="flex flex-col items-center justify-center py-16 text-center px-4 bg-neutral-900 border border-neutral-800 rounded-xl"
      >
        <div className="w-12 h-12 rounded-full bg-neutral-800 text-neutral-400 flex items-center justify-center mb-4">
          <Film className="w-6 h-6" />
        </div>
        <h3 className="text-base font-semibold text-neutral-100 mb-1">Catalog is empty</h3>
        <p className="text-sm text-neutral-400 max-w-md">No media titles are currently available in the catalog.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Filter and Search Bar */}
      <CatalogFilterBar
        filterState={filterState}
        onFilterChange={setFilterState}
        titles={titles}
        filteredCount={filteredTitles.length}
        totalLoadedCount={titles.length}
      />

      {/* Main Content Area */}
      {filteredTitles.length > 0 ? (
        <section aria-label="Media Catalog Grid">
          <div
            data-testid="catalog-list"
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6"
          >
            {filteredTitles.map((item: Title) => (
              <TitleCard key={item.id} title={item} repository={repository} />
            ))}
          </div>
        </section>
      ) : (
        /* Empty Filtered State */
        <div
          data-testid="catalog-empty-filtered"
          className="flex flex-col items-center justify-center py-16 text-center px-4 bg-neutral-900 border border-neutral-800 rounded-xl"
        >
          <div className="w-12 h-12 rounded-full bg-neutral-800 text-amber-400 flex items-center justify-center mb-4">
            <FilterX className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-neutral-100 mb-1">No matching titles found</h3>
          <p className="text-sm text-neutral-400 max-w-md mb-6">
            No loaded items match your current filter and search criteria. Try adjusting your filters or loading more items from the catalog.
          </p>
          <div className="flex flex-wrap gap-3 justify-center">
            <button
              onClick={() => setFilterState(DEFAULT_FILTER_STATE)}
              data-testid="clear-filters-button"
              className="inline-flex items-center gap-2 min-h-[44px] px-4 py-2 text-sm font-medium text-neutral-200 bg-neutral-800 border border-neutral-700 rounded-lg hover:bg-neutral-700 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer"
            >
              <RotateCcw className="w-4 h-4" />
              Reset Filters
            </button>
            {hasMore && (
              <button
                onClick={loadNextPage}
                disabled={isLoadingMore}
                data-testid="catalog-load-more-from-empty-button"
                className="inline-flex items-center gap-2 min-h-[44px] px-4 py-2 text-sm font-semibold text-neutral-950 bg-amber-500 rounded-lg hover:bg-amber-400 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-400 cursor-pointer disabled:opacity-50"
              >
                {isLoadingMore ? 'Loading...' : 'Load More Items from Server'}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Error state during loadNextPage */}
      {error && titles.length > 0 && (
        <div
          data-testid="catalog-error"
          className="flex items-center justify-between p-4 bg-red-950/60 border border-red-800 rounded-xl text-sm text-red-200"
        >
          <span>Failed to load next page: {error.message}</span>
          <button
            onClick={retry}
            data-testid="catalog-retry-button"
            className="inline-flex items-center gap-1.5 min-h-[44px] px-3.5 py-2 text-xs font-medium text-red-200 bg-red-900/40 border border-red-700 rounded-lg hover:bg-red-800/60 transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-red-400"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Retry
          </button>
        </div>
      )}

      {/* Pagination Footer */}
      <footer className="flex justify-center pt-4">
        {hasMore ? (
          <button
            onClick={loadNextPage}
            disabled={isLoadingMore}
            data-testid="catalog-load-more-button"
            className="inline-flex items-center gap-2 min-h-[44px] px-6 py-2.5 text-sm font-semibold text-neutral-200 bg-neutral-900 border border-neutral-700 rounded-lg shadow-sm hover:bg-neutral-800 hover:border-neutral-600 active:bg-neutral-950 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer"
          >
            {isLoadingMore ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
                <span data-testid="catalog-loading-more">Loading more...</span>
              </>
            ) : (
              'Load More'
            )}
          </button>
        ) : (
          <div data-testid="catalog-end-of-results" className="text-xs text-neutral-500 py-3">
            End of catalog
          </div>
        )}
      </footer>
    </div>
  );
};
