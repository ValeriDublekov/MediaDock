import { describe, it, expect } from 'vitest';
import { Title } from '../domain/catalog';
import {
  CatalogFilterState,
  DEFAULT_FILTER_STATE,
  filterAndSortTitles,
  extractAvailableCountries,
  extractAvailableQualities,
} from '../domain/catalogFilter';

describe('Pure Catalog Filter & Sort Logic', () => {
  const d1 = new Date('2026-08-05T12:00:00Z');
  const d2 = new Date('2026-08-04T12:00:00Z');
  const d3 = new Date('2026-08-03T12:00:00Z');

  const movie1: Title = {
    id: 'tt001',
    title: 'Inception',
    normalizedTitle: 'inception',
    year: 2010,
    mediaType: 'movie',
    firstSeenAt: d1,
    lastSeenAt: d1,
    updatedAt: d1,
    imdbRating: 8.8,
    imdbVotes: 2400000,
    genres: ['Action', 'Sci-Fi'],
    countries: ['USA', 'UK'],
    director: 'Christopher Nolan',
    plot: 'A thief who steals corporate secrets through the use of dream-sharing technology.',
    qualities: ['1080p', '2160p'],
  };

  const series1: Title = {
    id: 'tt002',
    title: 'Breaking Bad',
    normalizedTitle: 'breaking bad',
    year: 2008,
    mediaType: 'series',
    firstSeenAt: d2,
    lastSeenAt: d2,
    updatedAt: d2,
    imdbRating: 9.5,
    imdbVotes: 1900000,
    genres: ['Crime', 'Drama'],
    countries: ['USA'],
    director: 'Vince Gilligan',
    plot: 'A chemistry teacher diagnosed with inoperable lung cancer turns to manufacturing and selling methamphetamine.',
    qualities: ['1080p'],
  };

  const doc1: Title = {
    id: 'tt003',
    title: 'Planet Earth II',
    normalizedTitle: 'planet earth ii',
    year: 2016,
    mediaType: 'documentary',
    firstSeenAt: d3,
    lastSeenAt: d3,
    updatedAt: d3,
    imdbRating: 9.5,
    imdbVotes: 150000,
    genres: ['Documentary'],
    countries: ['UK'],
    director: 'David Attenborough',
    plot: 'Wildlife documentary series presented by David Attenborough.',
    qualities: ['2160p'],
  };

  const unratedMovie: Title = {
    id: 'tt004',
    title: 'Indie Short Film',
    normalizedTitle: 'indie short film',
    year: 2024,
    mediaType: 'short',
    firstSeenAt: d1,
    lastSeenAt: d1,
    updatedAt: d1,
    imdbRating: null,
    imdbVotes: null,
    genres: ['Drama'],
    countries: ['France'],
    director: 'Jean Dupont',
    plot: 'An experimental French short movie.',
    qualities: ['720p'],
  };

  const sampleCatalog: Title[] = [movie1, series1, doc1, unratedMovie];

  it('returns all items under default filter state', () => {
    const result = filterAndSortTitles(sampleCatalog, DEFAULT_FILTER_STATE);
    expect(result).toHaveLength(4);
    expect(result[0].id).toBe('tt001'); // newest lastSeenAt
  });

  it('filters by search query matching title, director, genre, or country', () => {
    // Match title
    const res1 = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      searchQuery: 'Inception',
    });
    expect(res1).toHaveLength(1);
    expect(res1[0].title).toBe('Inception');

    // Match director
    const res2 = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      searchQuery: 'Nolan',
    });
    expect(res2).toHaveLength(1);
    expect(res2[0].title).toBe('Inception');

    // Match genre
    const res3 = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      searchQuery: 'Sci-Fi',
    });
    expect(res3).toHaveLength(1);
    expect(res3[0].title).toBe('Inception');
  });

  it('filters by media type', () => {
    const resMovies = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      mediaTypes: ['movie'],
    });
    expect(resMovies).toHaveLength(1);
    expect(resMovies[0].id).toBe('tt001');

    const resSeries = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      mediaTypes: ['series'],
    });
    expect(resSeries).toHaveLength(1);
    expect(resSeries[0].id).toBe('tt002');
  });

  it('filters by country', () => {
    const resUK = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      selectedCountries: ['UK'],
    });
    expect(resUK).toHaveLength(2); // Inception & Planet Earth II
    expect(resUK.map((i) => i.id)).toEqual(['tt001', 'tt003']);
  });

  it('filters by quality tag', () => {
    const res4k = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      selectedQuality: '2160p',
    });
    expect(res4k).toHaveLength(2); // Inception & Planet Earth II
    expect(res4k.map((i) => i.id)).toEqual(['tt001', 'tt003']);
  });

  it('applies separate rating thresholds for movies vs series', () => {
    // minMovieRating: 9.0 -> excludes Inception (8.8), but Breaking Bad (9.5 series) passes
    const res = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      minMovieRating: 9.0,
      minSeriesRating: 8.0,
    });
    expect(res.map((i) => i.id)).toContain('tt002');
    expect(res.map((i) => i.id)).not.toContain('tt001');
  });

  it('applies minimum votes threshold', () => {
    const resHighVotes = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      minVotes: 1000000,
    });
    expect(resHighVotes.map((i) => i.id)).toEqual(['tt001', 'tt002']);
  });

  it('respects showWithoutRating flag', () => {
    const resWithUnrated = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      minMovieRating: 8.0,
      showWithoutRating: true,
    });
    expect(resWithUnrated.map((i) => i.id)).toContain('tt004'); // unrated allowed

    const resNoUnrated = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      minMovieRating: 8.0,
      showWithoutRating: false,
    });
    expect(resNoUnrated.map((i) => i.id)).not.toContain('tt004');
  });

  it('sorts by IMDb rating descending', () => {
    const res = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      sortBy: 'ratingDesc',
    });
    expect(res[0].id).toBe('tt002'); // Breaking Bad 9.5 (more votes than Planet Earth II)
    expect(res[1].id).toBe('tt003'); // Planet Earth II 9.5
    expect(res[2].id).toBe('tt001'); // Inception 8.8
    expect(res[3].id).toBe('tt004'); // unrated (-1)
  });

  it('sorts by title alphabetically', () => {
    const res = filterAndSortTitles(sampleCatalog, {
      ...DEFAULT_FILTER_STATE,
      sortBy: 'titleAsc',
    });
    expect(res.map((i) => i.title)).toEqual([
      'Breaking Bad',
      'Inception',
      'Indie Short Film',
      'Planet Earth II',
    ]);
  });

  it('extracts available countries and qualities correctly', () => {
    const countries = extractAvailableCountries(sampleCatalog);
    expect(countries).toEqual(['France', 'UK', 'USA']);

    const qualities = extractAvailableQualities(sampleCatalog);
    expect(qualities).toContain('1080p');
    expect(qualities).toContain('2160p');
    expect(qualities).toContain('720p');
  });
});
