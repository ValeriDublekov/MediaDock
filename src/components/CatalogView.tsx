import React, { useState, useMemo, useEffect } from 'react';
import { CatalogRepository, RssSourceType, Title } from '../domain/catalog';
import { useCatalog } from '../application/useCatalog';
import { useUserTitles } from '../application/useUserTitles';
import { firestoreCatalogAdapter } from '../adapters/firestoreCatalogAdapter';
import { firestoreSettingsAdapter } from '../adapters/firestoreSettingsAdapter';
import { CatalogFilterBar, CatalogViewMode } from './CatalogFilterBar';
import { TitleCard } from './TitleCard';
import { CatalogSkeleton } from './CatalogSkeleton';
import {
  CatalogFilterState,
  DEFAULT_LATEST_FILTER_STATE,
  filterAndSortTitles,
} from '../domain/catalogFilter';
import { AlertCircle, RefreshCw, Film, FilterX, Loader2, RotateCcw } from 'lucide-react';

interface CatalogViewProps {
  repository?: CatalogRepository;
  pageSize?: number;
}

export const CatalogView: React.FC<CatalogViewProps> = ({ repository = firestoreCatalogAdapter, pageSize = 16 }) => {
  const [viewMode, setViewMode] = useState<CatalogViewMode>('movies');
  const [filterState, setFilterState] = useState<CatalogFilterState>(DEFAULT_LATEST_FILTER_STATE);
  const [olderTitlesStarted, setOlderTitlesStarted] = useState(false);
  const rssSourceType: RssSourceType = viewMode === 'movies' ? 'movie' : 'series';

  const {
    titles: latestTitles,
    isLoading,
    error: latestError,
    retry: retryLatest,
    latestSnapshotAvailable,
  } = useCatalog({
    repository,
    pageSize,
    source: 'latest',
    rssSourceType,
  });

  const {
    titles: olderTitles,
    isLoading: isLoadingOlder,
    isLoadingMore: isLoadingMoreOlder,
    error: olderError,
    hasMore: hasMoreOlder,
    loadInitialPage: loadInitialOlderTitles,
    loadNextPage: loadNextOlderTitles,
    retry: retryOlderTitles,
  } = useCatalog({
    repository,
    pageSize,
    autoFetch: false,
    source: 'catalog',
    rssSourceType,
  });

  const {
    isFavorite,
    isIgnored,
    toggleFavorite,
    toggleIgnored,
  } = useUserTitles();

  const handleViewModeChange = (mode: CatalogViewMode) => {
    setViewMode(mode);
    setOlderTitlesStarted(false);
    setFilterState((previous) => ({ ...previous, sortBy: 'rssOrder' }));
  };

  const handleLoadOlderTitles = () => {
    if (!olderTitlesStarted) {
      setOlderTitlesStarted(true);
      void loadInitialOlderTitles();
      return;
    }
    void loadNextOlderTitles();
  };

  useEffect(() => {
    async function applySavedSettings() {
      try {
        const settings = await firestoreSettingsAdapter.getSettings();
        setFilterState((prev) => ({
          ...prev,
          minMovieRating: settings.minMovieRating !== undefined ? settings.minMovieRating : prev.minMovieRating,
          minSeriesRating: settings.minSeriesRating !== undefined ? settings.minSeriesRating : prev.minSeriesRating,
          minVotes: settings.minImdbVotes !== undefined ? settings.minImdbVotes : prev.minVotes,
        }));
      } catch (err) {
        console.warn('Failed to apply custom filter defaults from Firestore settings:', err);
      }
    }
    applySavedSettings();
  }, []);

  const titles = useMemo(() => {
    const combined = new Map<string, Title>();
    latestTitles.forEach((title) => combined.set(title.id, title));
    if (olderTitlesStarted) {
      olderTitles.forEach((title) => {
        if (!combined.has(title.id)) combined.set(title.id, title);
      });
    }
    return Array.from(combined.values());
  }, [latestTitles, olderTitles, olderTitlesStarted]);

  const filteredTitles = useMemo(() => {
    const visibleTitles = titles.filter((title) => !isIgnored(title.id));
    return filterAndSortTitles(visibleTitles, filterState);
  }, [titles, filterState, isIgnored]);

  const isPermissionError = latestError?.message.toLowerCase().includes('permission') || false;

  if (latestSnapshotAvailable === false && !isLoading && !latestError) {
    return (
      <div
        data-testid="catalog-no-latest-snapshot"
        className="flex flex-col items-center justify-center py-16 text-center px-4 bg-neutral-900 border border-neutral-800 rounded-xl"
      >
        <div className="w-12 h-12 rounded-full bg-neutral-800 text-amber-400 flex items-center justify-center mb-4">
          <Film className="w-6 h-6" />
        </div>
        <h3 className="text-base font-semibold text-neutral-100 mb-1">Няма успешно RSS сканиране</h3>
        <p className="text-sm text-neutral-400 max-w-md mb-6">
          Последните заглавия ще се появят след успешно сканиране на RSS feed-овете.
        </p>
      </div>
    );
  }

  if (isLoading) {
    return <CatalogSkeleton count={pageSize} />;
  }

  if (latestError && latestTitles.length === 0) {
    return (
      <div
        data-testid="catalog-error"
        className="flex flex-col items-center justify-center py-16 text-center px-4 bg-neutral-900 border border-neutral-800 rounded-xl"
      >
        <div className="w-12 h-12 rounded-full bg-red-950/50 border border-red-800/60 text-red-400 flex items-center justify-center mb-4">
          <AlertCircle className="w-6 h-6" />
        </div>
        <h3 className="text-base font-semibold text-neutral-100 mb-1">
          {isPermissionError ? 'Няма достъп до каталога' : 'Failed to load catalog'}
        </h3>
        <p className="text-sm text-neutral-400 max-w-md mb-6">
          {isPermissionError
            ? 'Проверете дали сте в allowlist-а и дали последните Firestore rules са deploy-нати. '
              + 'Необходим е read достъп до rssSnapshotState и rssSnapshots.'
            : latestError.message}
        </p>
        <button
          onClick={retryLatest}
          data-testid="catalog-retry-button"
          className="inline-flex items-center gap-2 min-h-[44px] px-5 py-2.5 text-sm font-medium text-neutral-200 bg-neutral-800 border border-neutral-700 rounded-lg hover:bg-neutral-700 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer"
        >
          <RefreshCw className="w-4 h-4" />
          Retry
        </button>
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
        viewMode={viewMode}
        onViewModeChange={handleViewModeChange}
      />

      {/* Main Content Area */}
      {filteredTitles.length > 0 ? (
        <section aria-label="Media Catalog Grid">
          <div
            data-testid="catalog-list"
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6"
          >
            {filteredTitles.map((item: Title) => (
              <TitleCard
                key={item.id}
                title={item}
                repository={repository}
                isFavorite={isFavorite(item.id)}
                isIgnored={isIgnored(item.id)}
                onToggleFavorite={toggleFavorite}
                onToggleIgnored={toggleIgnored}
              />
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
            <FilterX className="w-6 h-6 text-amber-400" />
          </div>
          <h3 className="text-base font-semibold text-neutral-100 mb-1">
            Няма намерени заглавия
          </h3>
          <p className="text-sm text-neutral-400 max-w-md mb-6">
            Няма заглавия от избраната RSS категория, които отговарят на текущите филтри.
          </p>
          <div className="flex flex-wrap gap-3 justify-center">
            <button
              onClick={() => setFilterState(DEFAULT_LATEST_FILTER_STATE)}
              data-testid="clear-filters-button"
              className="inline-flex items-center gap-2 min-h-[44px] px-4 py-2 text-sm font-medium text-neutral-200 bg-neutral-800 border border-neutral-700 rounded-lg hover:bg-neutral-700 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer"
            >
              <RotateCcw className="w-4 h-4" />
              Изчисти филтрите
            </button>
          </div>
        </div>
      )}

      {/* Error state during loadNextPage */}
      {olderError && (
        <div
          data-testid="catalog-error"
          className="flex items-center justify-between p-4 bg-red-950/60 border border-red-800 rounded-xl text-sm text-red-200"
        >
          <span>Неуспешно зареждане на по-стари заглавия: {olderError.message}</span>
          <button
            onClick={retryOlderTitles}
            data-testid="catalog-retry-button"
            className="inline-flex items-center gap-1.5 min-h-[44px] px-3.5 py-2 text-xs font-medium text-red-200 bg-red-900/40 border border-red-700 rounded-lg hover:bg-red-800/60 transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-red-400"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Retry
          </button>
        </div>
      )}

      <footer className="flex justify-center pt-4">
        {!olderTitlesStarted || hasMoreOlder ? (
          <button
            onClick={handleLoadOlderTitles}
            disabled={isLoadingOlder || isLoadingMoreOlder}
            data-testid="catalog-load-more-button"
            className="inline-flex items-center gap-2 min-h-[44px] px-6 py-2.5 text-sm font-semibold text-neutral-200 bg-neutral-900 border border-neutral-700 rounded-lg shadow-sm hover:bg-neutral-800 hover:border-neutral-600 active:bg-neutral-950 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer"
          >
            {isLoadingOlder || isLoadingMoreOlder ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
                <span>Зареждане...</span>
              </>
            ) : olderTitlesStarted ? (
              'Зареди още'
            ) : (
              'Зареди по-стари заглавия'
            )}
          </button>
        ) : (
          <div data-testid="catalog-end-of-results" className="text-xs text-neutral-500 py-3">
            Няма повече заглавия
          </div>
        )}
      </footer>
    </div>
  );
};
