import React, { useState } from 'react';
import {
  CatalogFilterState,
  DEFAULT_FILTER_STATE,
  DEFAULT_LATEST_FILTER_STATE,
  SortOption,
  extractAvailableCountries,
  extractAvailableQualities,
} from '../domain/catalogFilter';
import { Title } from '../domain/catalog';
import {
  Search,
  X,
  SlidersHorizontal,
  RotateCcw,
  Film,
  Tv,
  Video,
  Sparkles,
  Info,
  ChevronDown,
  ChevronUp,
  Star,
  EyeOff,
} from 'lucide-react';

export type CatalogViewMode = 'latest' | 'catalog' | 'favorites' | 'ignored';

interface CatalogFilterBarProps {
  filterState: CatalogFilterState;
  onFilterChange: (newState: CatalogFilterState) => void;
  titles: Title[];
  filteredCount: number;
  totalLoadedCount: number;
  viewMode?: CatalogViewMode;
  onViewModeChange?: (mode: CatalogViewMode) => void;
  favoritesCount?: number;
  ignoredCount?: number;
  isLatestMode?: boolean;
}

export const CatalogFilterBar: React.FC<CatalogFilterBarProps> = ({
  filterState,
  onFilterChange,
  titles,
  filteredCount,
  totalLoadedCount,
  viewMode = 'all',
  onViewModeChange,
  favoritesCount = 0,
  ignoredCount = 0,
  isLatestMode = false,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  const availableCountries = extractAvailableCountries(titles);
  const availableQualities = extractAvailableQualities(titles);

  const isFiltered =
    filterState.searchQuery !== '' ||
    (filterState.mediaTypes && filterState.mediaTypes.length > 0) ||
    (filterState.selectedCountries && filterState.selectedCountries.length > 0) ||
    filterState.selectedQuality !== 'All' ||
    filterState.minMovieRating > 0 ||
    filterState.minSeriesRating > 0 ||
    filterState.minVotes > 0 ||
    !filterState.showWithoutRating ||
    filterState.sortBy !== (isLatestMode ? 'rssOrder' : 'lastSeenDesc');

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onFilterChange({ ...filterState, searchQuery: e.target.value });
  };

  const handleClearSearch = () => {
    onFilterChange({ ...filterState, searchQuery: '' });
  };

  const ALL_MEDIA_TYPES = ['movie', 'series', 'documentary', 'short'];

  const handleMediaTypeToggle = (type: string) => {
    const current = filterState.mediaTypes || [];
    let updated: string[];
    if (current.length === 0) {
      // All were active, clicking type deselects it
      updated = ALL_MEDIA_TYPES.filter((t) => t !== type);
    } else if (current.includes(type)) {
      updated = current.filter((t) => t !== type);
      if (updated.length === 0) {
        updated = ['__none__'];
      }
    } else {
      updated = [...current, type];
      if (ALL_MEDIA_TYPES.every((t) => updated.includes(t))) {
        updated = [];
      }
    }
    onFilterChange({ ...filterState, mediaTypes: updated });
  };

  const handleBulkMediaType = (select: boolean) => {
    if (select) {
      onFilterChange({ ...filterState, mediaTypes: [] }); // Empty array means all enabled
    } else {
      onFilterChange({ ...filterState, mediaTypes: ['__none__'] }); // none matched
    }
  };

  const handleCountryToggle = (country: string) => {
    const current = filterState.selectedCountries || [];
    let updated: string[];
    if (current.length === 0) {
      // All countries were active, clicking country deselects it
      updated = availableCountries.filter((c) => c !== country);
    } else if (current.includes(country)) {
      updated = current.filter((c) => c !== country);
      if (updated.length === 0) {
        updated = ['__none__'];
      }
    } else {
      updated = [...current, country];
      if (availableCountries.every((c) => updated.includes(c))) {
        updated = [];
      }
    }
    onFilterChange({ ...filterState, selectedCountries: updated });
  };

  const handleBulkCountries = (select: boolean) => {
    if (select) {
      onFilterChange({ ...filterState, selectedCountries: [] });
    } else {
      onFilterChange({ ...filterState, selectedCountries: ['__none__'] });
    }
  };

  const handleReset = () => {
    onFilterChange(isLatestMode ? DEFAULT_LATEST_FILTER_STATE : DEFAULT_FILTER_STATE);
  };

  // Format vote counts for slider label (e.g., 500 -> 500, 5000 -> 5k)
  const formatVoteLabel = (val: number) => {
    if (val >= 1000) return `${(val / 1000).toFixed(0)}k`;
    return val.toString();
  };

  return (
    <div
      data-testid="catalog-filter-bar"
      className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 sm:p-5 shadow-sm space-y-4"
    >
      {/* View Mode Navigation Tabs */}
      {onViewModeChange && (
        <div
          data-testid="view-mode-tabs"
          className="flex items-center gap-2 p-1 bg-neutral-950 border border-neutral-800/80 rounded-xl overflow-x-auto"
        >
          <button
            type="button"
            onClick={() => onViewModeChange('latest')}
            data-testid="view-mode-latest"
            className={`min-h-[38px] px-4 py-2 text-xs font-bold rounded-lg flex items-center gap-2 transition-all cursor-pointer whitespace-nowrap ${
              viewMode === 'latest'
                ? 'bg-neutral-800 text-amber-400 border border-amber-500/40 shadow-sm'
                : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900'
            }`}
          >
            <Film className="w-4 h-4" />
            <span>Последни</span>
          </button>

          <button
            type="button"
            onClick={() => onViewModeChange('catalog')}
            data-testid="view-mode-catalog"
            className={`min-h-[38px] px-4 py-2 text-xs font-bold rounded-lg flex items-center gap-2 transition-all cursor-pointer whitespace-nowrap ${
              viewMode === 'catalog'
                ? 'bg-neutral-800 text-amber-400 border border-amber-500/40 shadow-sm'
                : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900'
            }`}
          >
            <Video className="w-4 h-4" />
            <span>Каталог</span>
          </button>

          <button
            type="button"
            onClick={() => onViewModeChange('favorites')}
            data-testid="view-mode-favorites"
            className={`min-h-[38px] px-4 py-2 text-xs font-bold rounded-lg flex items-center gap-2 transition-all cursor-pointer whitespace-nowrap ${
              viewMode === 'favorites'
                ? 'bg-amber-500 text-neutral-950 shadow-md font-extrabold'
                : 'text-neutral-400 hover:text-amber-400 hover:bg-neutral-900'
            }`}
          >
            <Star className={`w-4 h-4 ${viewMode === 'favorites' ? 'fill-neutral-950' : 'text-amber-400'}`} />
            <span>Любими</span>
            <span
              data-testid="favorites-count-badge"
              className={`text-[11px] px-1.5 py-0.2 rounded-full ${
                viewMode === 'favorites'
                  ? 'bg-neutral-950 text-amber-400'
                  : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
              }`}
            >
              {favoritesCount}
            </span>
          </button>

          <button
            type="button"
            onClick={() => onViewModeChange('ignored')}
            data-testid="view-mode-ignored"
            className={`min-h-[38px] px-4 py-2 text-xs font-bold rounded-lg flex items-center gap-2 transition-all cursor-pointer whitespace-nowrap ${
              viewMode === 'ignored'
                ? 'bg-red-950 text-red-200 border border-red-700 shadow-sm'
                : 'text-neutral-400 hover:text-red-400 hover:bg-neutral-900'
            }`}
          >
            <EyeOff className="w-4 h-4" />
            <span>Скрити</span>
            <span
              data-testid="ignored-count-badge"
              className={`text-[11px] px-1.5 py-0.2 rounded-full ${
                viewMode === 'ignored'
                  ? 'bg-red-900 text-red-100'
                  : 'bg-red-950/60 text-red-400 border border-red-900'
              }`}
            >
              {ignoredCount}
            </span>
          </button>
        </div>
      )}

      {/* Top Search & Controls Row */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        {/* Search Input Box */}
        <div className="relative flex-1 min-w-[240px]">
          <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-neutral-400">
            <Search className="w-4 h-4" />
          </div>
          <input
            type="search"
            id="catalog-search-input"
            data-testid="catalog-search-input"
            aria-label="Search catalog items by title, director, genre, or plot"
            placeholder="Search loaded titles, directors, genres..."
            value={filterState.searchQuery}
            onChange={handleSearchChange}
            className="w-full min-h-[44px] pl-10 pr-10 py-2.5 text-sm bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-100 placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-amber-500 transition-colors"
          />
          {filterState.searchQuery && (
            <button
              type="button"
              onClick={handleClearSearch}
              data-testid="catalog-search-clear"
              aria-label="Clear search text"
              className="absolute inset-y-0 right-0 pr-3 flex items-center text-neutral-400 hover:text-neutral-200 cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Sort Selector & Toggle Filters Button */}
        <div className="flex items-center gap-2">
          {/* Sort Selector */}
          <div className="flex items-center gap-2">
            <label htmlFor="catalog-sort-select" className="sr-only">
              Sort Catalog By
            </label>
            <select
              id="catalog-sort-select"
              data-testid="catalog-sort-select"
              value={filterState.sortBy}
              onChange={(e) =>
                onFilterChange({ ...filterState, sortBy: e.target.value as SortOption })
              }
              aria-label="Sort catalog items"
              className="min-h-[44px] px-3 py-2 text-xs font-semibold bg-neutral-950 border border-neutral-800 text-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer"
            >
              <option value="rssOrder">RSS order</option>
              <option value="lastSeenDesc">Newest First</option>
              <option value="lastSeenAsc">Oldest First</option>
              <option value="ratingDesc">Highest IMDb Rating</option>
              <option value="votesDesc">Most IMDb Votes</option>
              <option value="titleAsc">Title (A-Z)</option>
              <option value="yearDesc">Release Year (Newest)</option>
            </select>
          </div>

          {/* Toggle Expand Filters Button */}
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            data-testid="toggle-filters-expand"
            aria-expanded={isExpanded}
            aria-label="Toggle filter options"
            className={`min-h-[44px] px-3.5 py-2 text-xs font-semibold rounded-lg border flex items-center gap-1.5 transition-colors cursor-pointer ${
              isFiltered || isExpanded
                ? 'bg-amber-500/10 text-amber-400 border-amber-500/40 hover:bg-amber-500/20'
                : 'bg-neutral-800 text-neutral-300 border-neutral-700 hover:bg-neutral-700'
            }`}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            <span>Filters</span>
            {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>

          {/* Reset Filters Button */}
          {isFiltered && (
            <button
              type="button"
              onClick={handleReset}
              data-testid="reset-filters-button"
              aria-label="Reset all filters"
              className="min-h-[44px] px-3 py-2 text-xs font-medium text-neutral-400 hover:text-neutral-200 border border-neutral-800 hover:border-neutral-700 rounded-lg flex items-center gap-1 transition-colors cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Reset</span>
            </button>
          )}
        </div>
      </div>

      {/* Search Scope Notice Banner */}
      <div
        data-testid="search-scope-notice"
        className="flex items-center justify-between px-3 py-2 bg-neutral-950/60 border border-neutral-800/80 rounded-lg text-xs text-neutral-400"
      >
        <div className="flex items-center gap-2">
          <Info className="w-3.5 h-3.5 text-amber-400/80 shrink-0" />
          <span>
            Search and filters apply to {filteredCount} of {totalLoadedCount} loaded items
          </span>
        </div>
        {isFiltered && (
          <span className="text-[11px] font-medium text-amber-400 bg-amber-950/50 px-2 py-0.5 rounded border border-amber-800/50">
            Active Filters
          </span>
        )}
      </div>

      {/* Expanded Filter Panel */}
      {isExpanded && (
        <div
          data-testid="filter-panel-content"
          className="pt-3 border-t border-neutral-800 space-y-4 animate-in fade-in duration-200"
        >
          {/* Media Types Filter Row */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs font-medium text-neutral-400">
              <span>Media Types</span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleBulkMediaType(true)}
                  data-testid="media-type-bulk-all"
                  className="text-[11px] text-amber-400 hover:underline cursor-pointer"
                >
                  All
                </button>
                <span>|</span>
                <button
                  type="button"
                  onClick={() => handleBulkMediaType(false)}
                  data-testid="media-type-bulk-none"
                  className="text-[11px] text-neutral-400 hover:text-neutral-200 cursor-pointer"
                >
                  None
                </button>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {[
                { key: 'movie', label: 'Movie', icon: Film },
                { key: 'series', label: 'TV Series', icon: Tv },
                { key: 'documentary', label: 'Documentary', icon: Video },
                { key: 'short', label: 'Short Movie', icon: Sparkles },
              ].map(({ key, label, icon: Icon }) => {
                const active =
                  !filterState.mediaTypes ||
                  filterState.mediaTypes.length === 0 ||
                  filterState.mediaTypes.includes(key);
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => handleMediaTypeToggle(key)}
                    data-testid={`filter-mediatype-${key}`}
                    aria-pressed={active}
                    className={`min-h-[38px] px-3 py-1.5 rounded-lg text-xs font-semibold border flex items-center gap-1.5 transition-colors cursor-pointer ${
                      active
                        ? 'bg-neutral-800 text-amber-400 border-amber-500/50 shadow-xs'
                        : 'bg-neutral-950 text-neutral-500 border-neutral-800 hover:text-neutral-300'
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    <span>{label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Rating & Votes Sliders Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 bg-neutral-950 p-3.5 rounded-lg border border-neutral-800/80">
            {/* Min Movie Rating Slider */}
            <div className="space-y-1.5">
              <div className="flex justify-between items-center text-xs">
                <label htmlFor="min-movie-rating-slider" className="text-neutral-300 font-medium">
                  🎬 Min Movie Rating
                </label>
                <span data-testid="val-movie-rating" className="font-mono font-bold text-amber-400">
                  {filterState.minMovieRating > 0 ? filterState.minMovieRating.toFixed(1) : 'Any'}
                </span>
              </div>
              <input
                type="range"
                id="min-movie-rating-slider"
                data-testid="min-movie-rating-slider"
                min="0"
                max="10"
                step="0.1"
                value={filterState.minMovieRating}
                onChange={(e) =>
                  onFilterChange({ ...filterState, minMovieRating: parseFloat(e.target.value) })
                }
                className="w-full h-1.5 bg-neutral-800 rounded-lg appearance-none cursor-pointer accent-amber-500"
              />
            </div>

            {/* Min Series Rating Slider */}
            <div className="space-y-1.5">
              <div className="flex justify-between items-center text-xs">
                <label htmlFor="min-series-rating-slider" className="text-neutral-300 font-medium">
                  📺 Min Series Rating
                </label>
                <span data-testid="val-series-rating" className="font-mono font-bold text-amber-400">
                  {filterState.minSeriesRating > 0 ? filterState.minSeriesRating.toFixed(1) : 'Any'}
                </span>
              </div>
              <input
                type="range"
                id="min-series-rating-slider"
                data-testid="min-series-rating-slider"
                min="0"
                max="10"
                step="0.1"
                value={filterState.minSeriesRating}
                onChange={(e) =>
                  onFilterChange({ ...filterState, minSeriesRating: parseFloat(e.target.value) })
                }
                className="w-full h-1.5 bg-neutral-800 rounded-lg appearance-none cursor-pointer accent-amber-500"
              />
            </div>

            {/* Min Votes Slider */}
            <div className="space-y-1.5">
              <div className="flex justify-between items-center text-xs">
                <label htmlFor="min-votes-slider" className="text-neutral-300 font-medium">
                  👥 Min IMDb Votes
                </label>
                <span data-testid="val-votes" className="font-mono font-bold text-amber-400">
                  {filterState.minVotes > 0 ? formatVoteLabel(filterState.minVotes) : 'Any'}
                </span>
              </div>
              <input
                type="range"
                id="min-votes-slider"
                data-testid="min-votes-slider"
                min="0"
                max="50000"
                step="500"
                value={filterState.minVotes}
                onChange={(e) =>
                  onFilterChange({ ...filterState, minVotes: parseInt(e.target.value, 10) })
                }
                className="w-full h-1.5 bg-neutral-800 rounded-lg appearance-none cursor-pointer accent-amber-500"
              />
            </div>

            {/* Include Unrated Checkbox */}
            <div className="sm:col-span-2 lg:col-span-3 flex items-center gap-2 pt-1">
              <input
                type="checkbox"
                id="show-unrated-checkbox"
                data-testid="show-unrated-checkbox"
                checked={filterState.showWithoutRating}
                onChange={(e) =>
                  onFilterChange({ ...filterState, showWithoutRating: e.target.checked })
                }
                className="w-4 h-4 rounded border-neutral-700 bg-neutral-900 text-amber-500 focus:ring-amber-500 cursor-pointer"
              />
              <label
                htmlFor="show-unrated-checkbox"
                className="text-xs text-neutral-300 cursor-pointer select-none"
              >
                Include items without IMDb rating or votes
              </label>
            </div>
          </div>

          {/* Quality & Countries Selection Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Quality Selector */}
            <div className="space-y-1.5">
              <label htmlFor="quality-filter-select" className="text-xs font-medium text-neutral-400">
                Torrent Quality Tag
              </label>
              <select
                id="quality-filter-select"
                data-testid="quality-filter-select"
                value={filterState.selectedQuality}
                onChange={(e) =>
                  onFilterChange({ ...filterState, selectedQuality: e.target.value })
                }
                aria-label="Filter by torrent quality"
                className="w-full min-h-[44px] px-3 py-2 text-xs font-medium bg-neutral-950 border border-neutral-800 text-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer"
              >
                {availableQualities.map((qual) => (
                  <option key={qual} value={qual}>
                    {qual === 'All' ? 'All Qualities' : qual}
                  </option>
                ))}
              </select>
            </div>

            {/* Countries Toggle Buttons */}
            {availableCountries.length > 0 && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs font-medium text-neutral-400">
                  <span>Country of Origin</span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleBulkCountries(true)}
                      data-testid="country-bulk-all"
                      className="text-[11px] text-amber-400 hover:underline cursor-pointer"
                    >
                      All
                    </button>
                    <span>|</span>
                    <button
                      type="button"
                      onClick={() => handleBulkCountries(false)}
                      data-testid="country-bulk-none"
                      className="text-[11px] text-neutral-400 hover:text-neutral-200 cursor-pointer"
                    >
                      None
                    </button>
                  </div>
                </div>

                <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto p-1.5 bg-neutral-950 rounded-lg border border-neutral-800">
                  {availableCountries.map((country) => {
                    const active =
                      !filterState.selectedCountries ||
                      filterState.selectedCountries.length === 0 ||
                      filterState.selectedCountries.includes(country);
                    return (
                      <button
                        key={country}
                        type="button"
                        onClick={() => handleCountryToggle(country)}
                        data-testid={`filter-country-${country}`}
                        aria-pressed={active}
                        className={`px-2.5 py-1 rounded text-[11px] font-medium border transition-colors cursor-pointer ${
                          active
                            ? 'bg-amber-500/20 text-amber-300 border-amber-500/50'
                            : 'bg-neutral-900 text-neutral-500 border-neutral-800 hover:text-neutral-300'
                        }`}
                      >
                        {country}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
