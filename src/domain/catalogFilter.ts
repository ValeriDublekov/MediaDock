import { Title } from './catalog';

export type SortOption =
  | 'lastSeenDesc'
  | 'lastSeenAsc'
  | 'ratingDesc'
  | 'votesDesc'
  | 'titleAsc'
  | 'yearDesc';

export interface CatalogFilterState {
  searchQuery: string;
  mediaTypes: string[]; // e.g. ['movie', 'series', 'documentary', 'short']. Empty array means all enabled
  selectedCountries: string[]; // Empty array means all countries enabled
  selectedQuality: string; // 'All' or specific quality e.g. '1080p'
  minMovieRating: number; // 0.0 - 10.0
  minSeriesRating: number; // 0.0 - 10.0
  minVotes: number; // 0+
  showWithoutRating: boolean; // default true
  sortBy: SortOption; // default 'lastSeenDesc'
}

export const DEFAULT_FILTER_STATE: CatalogFilterState = {
  searchQuery: '',
  mediaTypes: [],
  selectedCountries: [],
  selectedQuality: 'All',
  minMovieRating: 0,
  minSeriesRating: 0,
  minVotes: 0,
  showWithoutRating: true,
  sortBy: 'lastSeenDesc',
};

export function normalizeMediaType(type: string): string {
  const lower = (type || '').toLowerCase().trim();
  if (lower === 'movie') return 'movie';
  if (lower === 'series' || lower === 'tv series') return 'series';
  if (lower === 'documentary') return 'documentary';
  if (lower === 'short' || lower === 'short movie') return 'short';
  return lower;
}

export function extractAvailableCountries(items: Title[]): string[] {
  const countrySet = new Set<string>();
  items.forEach((item) => {
    if (item.countries && Array.isArray(item.countries)) {
      item.countries.forEach((c) => {
        const trimmed = c.trim();
        if (trimmed && trimmed !== 'N/A') {
          countrySet.add(trimmed);
        }
      });
    }
  });
  return Array.from(countrySet).sort((a, b) => a.localeCompare(b));
}

export function extractAvailableQualities(items: Title[]): string[] {
  const qualitySet = new Set<string>(['All', '1080p', '2160p', '720p', 'WEB-DL', 'HDRip']);
  items.forEach((item) => {
    if (item.qualities) {
      item.qualities.forEach((q) => {
        if (q && q.trim()) qualitySet.add(q.trim());
      });
    }
    if (item.occurrences) {
      item.occurrences.forEach((occ) => {
        if (occ.quality && occ.quality.trim()) {
          qualitySet.add(occ.quality.trim());
        }
      });
    }
  });
  return Array.from(qualitySet);
}

export function sortTitles(titles: Title[], sortBy: SortOption): Title[] {
  return [...titles].sort((a, b) => {
    switch (sortBy) {
      case 'lastSeenDesc': {
        const timeA = new Date(a.lastSeenAt).getTime();
        const timeB = new Date(b.lastSeenAt).getTime();
        if (timeA !== timeB) return timeB - timeA;
        
        // Fallback to year descending if lastSeenAt is identical
        const yearA = typeof a.year === 'number' ? a.year : -1;
        const yearB = typeof b.year === 'number' ? b.year : -1;
        if (yearA !== yearB) return yearB - yearA;

        return b.id.localeCompare(a.id);
      }
      case 'lastSeenAsc': {
        const timeA = new Date(a.lastSeenAt).getTime();
        const timeB = new Date(b.lastSeenAt).getTime();
        if (timeA !== timeB) return timeA - timeB;

        // Fallback to year ascending if lastSeenAt is identical
        const yearA = typeof a.year === 'number' ? a.year : -1;
        const yearB = typeof b.year === 'number' ? b.year : -1;
        if (yearA !== yearB) return yearA - yearB;

        return a.id.localeCompare(b.id);
      }
      case 'ratingDesc': {
        const ratingA = typeof a.imdbRating === 'number' ? a.imdbRating : -1;
        const ratingB = typeof b.imdbRating === 'number' ? b.imdbRating : -1;
        if (ratingA !== ratingB) return ratingB - ratingA;
        const votesA = typeof a.imdbVotes === 'number' ? a.imdbVotes : 0;
        const votesB = typeof b.imdbVotes === 'number' ? b.imdbVotes : 0;
        if (votesA !== votesB) return votesB - votesA;
        return a.title.localeCompare(b.title);
      }
      case 'votesDesc': {
        const votesA = typeof a.imdbVotes === 'number' ? a.imdbVotes : -1;
        const votesB = typeof b.imdbVotes === 'number' ? b.imdbVotes : -1;
        if (votesA !== votesB) return votesB - votesA;
        const ratingA = typeof a.imdbRating === 'number' ? a.imdbRating : -1;
        const ratingB = typeof b.imdbRating === 'number' ? b.imdbRating : -1;
        if (ratingA !== ratingB) return ratingB - ratingA;
        return a.title.localeCompare(b.title);
      }
      case 'titleAsc': {
        return a.title.localeCompare(b.title);
      }
      case 'yearDesc': {
        const yearA = typeof a.year === 'number' ? a.year : -1;
        const yearB = typeof b.year === 'number' ? b.year : -1;
        if (yearA !== yearB) return yearB - yearA;
        return a.title.localeCompare(b.title);
      }
      default:
        return 0;
    }
  });
}

export function filterAndSortTitles(items: Title[], filter: CatalogFilterState): Title[] {
  const filtered = items.filter((title) => {
    // 1. Search Query
    if (filter.searchQuery && filter.searchQuery.trim() !== '') {
      const q = filter.searchQuery.toLowerCase().trim();
      const titleMatch = title.title.toLowerCase().includes(q);
      const dirMatch = title.director ? title.director.toLowerCase().includes(q) : false;
      const genreMatch = title.genres ? title.genres.some((g) => g.toLowerCase().includes(q)) : false;
      const plotMatch = title.plot ? title.plot.toLowerCase().includes(q) : false;
      const countryMatch = title.countries
        ? title.countries.some((c) => c.toLowerCase().includes(q))
        : false;
      const yearMatch = title.year ? title.year.toString().includes(q) : false;

      if (!titleMatch && !dirMatch && !genreMatch && !plotMatch && !countryMatch && !yearMatch) {
        return false;
      }
    }

    // 2. Media Type Filter
    if (filter.mediaTypes && filter.mediaTypes.length > 0) {
      const itemTypeNormalized = normalizeMediaType(title.mediaType);
      const allowedTypesNormalized = filter.mediaTypes.map(normalizeMediaType);
      if (!allowedTypesNormalized.includes(itemTypeNormalized)) {
        return false;
      }
    }

    // 3. Country Filter
    if (filter.selectedCountries && filter.selectedCountries.length > 0) {
      if (!title.countries || title.countries.length === 0) {
        return false;
      }
      const titleCountriesLower = title.countries.map((c) => c.toLowerCase().trim());
      const selectedLower = filter.selectedCountries.map((c) => c.toLowerCase().trim());
      const matchesCountry = titleCountriesLower.some((tc) => selectedLower.includes(tc));
      if (!matchesCountry) {
        return false;
      }
    }

    // 4. Quality Filter
    if (filter.selectedQuality && filter.selectedQuality !== 'All') {
      const targetQual = filter.selectedQuality.toLowerCase().trim();
      let matchesQuality = false;

      if (title.qualities && title.qualities.some((q) => q.toLowerCase().includes(targetQual))) {
        matchesQuality = true;
      }
      if (!matchesQuality && title.occurrences) {
        matchesQuality = title.occurrences.some(
          (occ) =>
            (occ.quality && occ.quality.toLowerCase().includes(targetQual)) ||
            (occ.rawTitle && occ.rawTitle.toLowerCase().includes(targetQual))
        );
      }
      if (!matchesQuality && title.title.toLowerCase().includes(targetQual)) {
        matchesQuality = true;
      }

      if (!matchesQuality) {
        return false;
      }
    }

    // 5. Rating & Votes Thresholds
    const isSeries = normalizeMediaType(title.mediaType) === 'series';
    const ratingThreshold = isSeries ? filter.minSeriesRating : filter.minMovieRating;
    const hasRating = typeof title.imdbRating === 'number' && !isNaN(title.imdbRating);

    if (!hasRating) {
      if (!filter.showWithoutRating) {
        return false;
      }
      if (filter.minVotes > 0) {
        return false;
      }
    } else {
      if (title.imdbRating! < ratingThreshold) {
        return false;
      }
      if (filter.minVotes > 0) {
        const votes = typeof title.imdbVotes === 'number' ? title.imdbVotes : 0;
        if (votes < filter.minVotes) {
          return false;
        }
      }
    }

    return true;
  });

  return sortTitles(filtered, filter.sortBy);
}
