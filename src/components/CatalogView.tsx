import React, { useState, useMemo, useEffect } from 'react';
import { CatalogRepository, Title } from '../domain/catalog';
import { useCatalog } from '../application/useCatalog';
import { useUserTitles } from '../application/useUserTitles';
import { firestoreCatalogAdapter } from '../adapters/firestoreCatalogAdapter';
import { firestoreSettingsAdapter } from '../adapters/firestoreSettingsAdapter';
import { CatalogFilterBar, CatalogViewMode } from './CatalogFilterBar';
import { TitleCard } from './TitleCard';
import { CatalogSkeleton } from './CatalogSkeleton';
import {
  CatalogFilterState,
  DEFAULT_FILTER_STATE,
  DEFAULT_LATEST_FILTER_STATE,
  filterAndSortTitles,
} from '../domain/catalogFilter';
import { AlertCircle, RefreshCw, Film, Loader2, FilterX, RotateCcw, Star, EyeOff, Video } from 'lucide-react';

interface CatalogViewProps {
  repository?: CatalogRepository;
  pageSize?: number;
}

export const CatalogView: React.FC<CatalogViewProps> = ({ repository = firestoreCatalogAdapter, pageSize = 16 }) => {
  const [viewMode, setViewMode] = useState<CatalogViewMode>('latest');
  const [filterState, setFilterState] = useState<CatalogFilterState>(DEFAULT_LATEST_FILTER_STATE);
  const isLatestMode = viewMode !== 'catalog';

  const {
    titles,
    isLoading,
    isLoadingMore,
    error,
    hasMore,
    isEmpty,
    loadNextPage,
    retry,
    latestSnapshotAvailable,
  } = useCatalog({
    repository,
    pageSize,
    source: isLatestMode ? 'latest' : 'catalog',
  });

  const {
    isFavorite,
    isIgnored,
    toggleFavorite,
    toggleIgnored,
    favoriteTitleIds,
    ignoredTitleIds,
  } = useUserTitles();

  const [extraTitles, setExtraTitles] = useState<Title[]>([]);

  const handleViewModeChange = (mode: CatalogViewMode) => {
    setViewMode(mode);
    setFilterState((previous) => {
      if (mode !== 'catalog' && previous.sortBy === 'lastSeenDesc') {
        return { ...previous, sortBy: 'rssOrder' };
      }
      if (mode === 'catalog' && previous.sortBy === 'rssOrder') {
        return { ...previous, sortBy: 'lastSeenDesc' };
      }
      return previous;
    });
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

  // Fetch missing titles for favorites/ignored if they are not loaded in the standard pagination pool yet
  useEffect(() => {
    async function fetchMissingUserTitles() {
      if (!repository.getTitlesByIds) return;
      const targetIds = viewMode === 'favorites' ? favoriteTitleIds : viewMode === 'ignored' ? ignoredTitleIds : [];
      if (targetIds.length === 0) return;

      const loadedIds = new Set([...titles.map((t) => t.id), ...extraTitles.map((t) => t.id)]);
      const missingIds = targetIds.filter((id) => !loadedIds.has(id));

      if (missingIds.length > 0) {
        try {
          const fetched = await repository.getTitlesByIds(missingIds);
          setExtraTitles((prev) => [...prev, ...fetched]);
        } catch (err) {
          console.error('Failed to fetch user titles by ID:', err);
        }
      }
    }
    fetchMissingUserTitles();
  }, [viewMode, favoriteTitleIds, ignoredTitleIds, titles, repository, extraTitles]);

  // Combine loaded pagination titles and extra user titles
  const combinedTitles = useMemo(() => {
    const map = new Map<string, Title>();
    titles.forEach((t) => map.set(t.id, t));
    if (viewMode === 'favorites' || viewMode === 'ignored') {
      extraTitles.forEach((t) => map.set(t.id, t));
    }
    return Array.from(map.values());
  }, [titles, extraTitles, viewMode]);

  const filteredTitles = useMemo(() => {
    let baseList = combinedTitles;

    if (viewMode === 'latest' || viewMode === 'catalog') {
      // Ignored titles are strictly hidden in the main list
      baseList = baseList.filter((t) => !isIgnored(t.id));
    } else if (viewMode === 'favorites') {
      baseList = baseList.filter((t) => isFavorite(t.id));
    } else if (viewMode === 'ignored') {
      baseList = baseList.filter((t) => isIgnored(t.id));
    }

    return filterAndSortTitles(baseList, filterState);
  }, [combinedTitles, viewMode, filterState, isFavorite, isIgnored]);

  const isPermissionError = error?.message.toLowerCase().includes('permission') || false;

  if (viewMode === 'latest' && latestSnapshotAvailable === false && !isLoading && !error) {
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
        <button
          onClick={() => handleViewModeChange('catalog')}
          data-testid="open-catalog-from-no-snapshot"
          className="inline-flex items-center gap-2 min-h-[44px] px-4 py-2 text-sm font-semibold text-neutral-950 bg-amber-500 rounded-lg hover:bg-amber-400 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-400 cursor-pointer"
        >
          <Video className="w-4 h-4" />
          Отвори каталога
        </button>
      </div>
    );
  }

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
        <h3 className="text-base font-semibold text-neutral-100 mb-1">
          {isPermissionError ? 'Няма достъп до каталога' : 'Failed to load catalog'}
        </h3>
        <p className="text-sm text-neutral-400 max-w-md mb-6">
          {isPermissionError
            ? 'Проверете дали сте в allowlist-а и дали последните Firestore rules са deploy-нати. '
              + 'Необходим е read достъп до rssSnapshotState и rssSnapshots.'
            : error.message}
        </p>
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
        titles={combinedTitles}
        filteredCount={filteredTitles.length}
        totalLoadedCount={combinedTitles.length}
        viewMode={viewMode}
        onViewModeChange={handleViewModeChange}
        favoritesCount={favoriteTitleIds.length}
        ignoredCount={ignoredTitleIds.length}
        isLatestMode={isLatestMode}
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
            {viewMode === 'favorites' ? (
              <Star className="w-6 h-6 text-amber-400" />
            ) : viewMode === 'ignored' ? (
              <EyeOff className="w-6 h-6 text-red-400" />
            ) : (
              <FilterX className="w-6 h-6 text-amber-400" />
            )}
          </div>
          <h3 className="text-base font-semibold text-neutral-100 mb-1">
            {viewMode === 'favorites'
              ? 'Нямате добавени любими филми'
              : viewMode === 'ignored'
              ? 'Нямате скрити филми'
              : 'No matching titles found'}
          </h3>
          <p className="text-sm text-neutral-400 max-w-md mb-6">
            {viewMode === 'favorites'
              ? 'Маркирайте филми със звезда ⭐ в каталога, за да се показват тук.'
              : viewMode === 'ignored'
              ? 'Филмите, които маркирате като скрити, ще се съхраняват тук и няма да се показват в основния каталог.'
              : 'Няма заредени филми, отговарящи на текущите критерии. Опитайте с нови филтри.'}
          </p>
          <div className="flex flex-wrap gap-3 justify-center">
            {viewMode === 'favorites' || viewMode === 'ignored' ? (
              <button
                onClick={() => handleViewModeChange('latest')}
                data-testid="back-to-all-button"
                className="inline-flex items-center gap-2 min-h-[44px] px-4 py-2 text-sm font-semibold text-neutral-950 bg-amber-500 rounded-lg hover:bg-amber-400 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-400 cursor-pointer"
              >
                <Film className="w-4 h-4" />
                Към всички филми
              </button>
            ) : (
              <>
                <button
                  onClick={() => setFilterState(isLatestMode ? DEFAULT_LATEST_FILTER_STATE : DEFAULT_FILTER_STATE)}
                  data-testid="clear-filters-button"
                  className="inline-flex items-center gap-2 min-h-[44px] px-4 py-2 text-sm font-medium text-neutral-200 bg-neutral-800 border border-neutral-700 rounded-lg hover:bg-neutral-700 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer"
                >
                  <RotateCcw className="w-4 h-4" />
                  Изчисти филтрите
                </button>
                {hasMore && (
                  <button
                    onClick={loadNextPage}
                    disabled={isLoadingMore}
                    data-testid="catalog-load-more-from-empty-button"
                    className="inline-flex items-center gap-2 min-h-[44px] px-4 py-2 text-sm font-semibold text-neutral-950 bg-amber-500 rounded-lg hover:bg-amber-400 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-400 cursor-pointer disabled:opacity-50"
                  >
                    {isLoadingMore ? 'Зареждане...' : 'Зареди още от сървъра'}
                  </button>
                )}
              </>
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
