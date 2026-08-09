import { Title, Occurrence } from '../domain/catalog';
import { getDb, getAuth } from './firebaseApp';
import { Timestamp } from 'firebase/firestore';
import { firestoreManualMappingAdapter } from './firestoreManualMappingAdapter';

export interface OmdbMovieResult {
  title: string;
  year: number | null;
  imdbId: string | null;
  mediaType: string;
  rating: number | null;
  votes: number | null;
  metascore: number | null;
  genres: string[];
  countries: string[];
  director: string | null;
  plot: string | null;
  posterUrl: string | null;
  runtime: string | null;
  awards: string | null;
  boxOffice: string | null;
  ratings: { source: string; value: string }[];
  rawPayload: any;
}

const parseYear = (yearStr: string | null | undefined): number | null => {
  if (!yearStr || yearStr === 'N/A') return null;
  const match = yearStr.match(/\d{4}/);
  return match ? parseInt(match[0], 10) : null;
};

const parseFloatVal = (val: string | null | undefined): number | null => {
  if (!val || val === 'N/A') return null;
  const parsed = parseFloat(val);
  return isNaN(parsed) ? null : parsed;
};

const parseIntWithCommas = (val: string | null | undefined): number | null => {
  if (!val || val === 'N/A') return null;
  const parsed = parseInt(val.replace(/,/g, ''), 10);
  return isNaN(parsed) ? null : parsed;
};

const parseIntVal = (val: string | null | undefined): number | null => {
  if (!val || val === 'N/A') return null;
  const parsed = parseInt(val, 10);
  return isNaN(parsed) ? null : parsed;
};

const parseList = (val: string | null | undefined): string[] => {
  if (!val || val === 'N/A') return [];
  return val.split(',').map((s) => s.trim()).filter((s) => s.length > 0);
};

const parseString = (val: string | null | undefined): string | null => {
  if (!val || val === 'N/A') return null;
  return val;
};

const determineMediaType = (omdbType: string, genres: string[]): string => {
  if (genres.some((g) => g.toLowerCase() === 'documentary')) return 'documentary';
  if (genres.some((g) => g.toLowerCase() === 'short')) return 'short';
  if (omdbType.toLowerCase() === 'series') return 'series';
  return 'movie';
};

const normalizePayload = (data: any): OmdbMovieResult => {
  const genres = parseList(data.Genre);
  const mediaType = determineMediaType(data.Type || 'movie', genres);
  
  return {
    title: data.Title || '',
    year: parseYear(data.Year),
    imdbId: parseString(data.imdbID),
    mediaType,
    rating: parseFloatVal(data.imdbRating),
    votes: parseIntWithCommas(data.imdbVotes),
    metascore: parseIntVal(data.Metascore),
    genres,
    countries: parseList(data.Country),
    director: parseString(data.Director),
    plot: parseString(data.Plot),
    posterUrl: parseString(data.Poster),
    runtime: parseString(data.Runtime),
    awards: parseString(data.Awards),
    boxOffice: parseString(data.BoxOffice),
    ratings: Array.isArray(data.Ratings) 
      ? data.Ratings.map((r: any) => ({ source: r.Source, value: r.Value }))
      : [],
    rawPayload: data,
  };
};

export const fetchFromOmdb = async (imdbId: string, apiKey: string): Promise<OmdbMovieResult> => {
  const res = await fetch(`https://www.omdbapi.com/?apikey=${encodeURIComponent(apiKey)}&i=${encodeURIComponent(imdbId)}`);
  if (!res.ok) {
    throw new Error(`OMDb API Error: ${res.statusText}`);
  }
  const data = await res.json();
  if (data.Response === 'False') {
    throw new Error(`OMDb Error: ${data.Error}`);
  }
  return normalizePayload(data);
};

// Crypto logic for SHA-256
async function sha256(message: string): Promise<string> {
  const msgBuffer = new TextEncoder().encode(message);
  const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  return hashHex;
}

const normalizeTitleForId = (title: string): string => {
  if (!title) return '';
  return title.trim().toLowerCase().replace(/\s+/g, ' ');
};

const getFallbackTitleId = async (normalizedTitle: string, year: number | null, mediaType: string): Promise<string> => {
  const yearStr = year !== null ? year.toString() : '';
  const rawStr = `v1:${normalizedTitle}:${yearStr}:${mediaType.toLowerCase()}`;
  return sha256(rawStr);
};

const getCacheKey = async (lookupTitle: string, lookupYear: number | null): Promise<string> => {
  const normTitle = normalizeTitleForId(lookupTitle);
  const yearStr = lookupYear !== null ? lookupYear.toString() : '';
  const rawStr = `v1:cache:${normTitle}:${yearStr}`;
  return sha256(rawStr);
};

export const updateTitleWithOmdb = async (oldTitle: Title, imdbId: string, apiKey: string): Promise<Title> => {
  // 1. Fetch from OMDb
  const omdbData = await fetchFromOmdb(imdbId, apiKey);
  const newImdbId = omdbData.imdbId || imdbId;
  
  // 2. Determine new ID
  const newTitleId = newImdbId.toLowerCase();
  
  // 3. Prepare updated title object
  const now = new Date();
  const updatedTitleData: Partial<Title> = {
    title: omdbData.title,
    normalizedTitle: normalizeTitleForId(omdbData.title),
    year: omdbData.year,
    mediaType: omdbData.mediaType,
    updatedAt: now,
    imdbId: omdbData.imdbId,
    imdbRating: omdbData.rating,
    imdbVotes: omdbData.votes,
    metascore: omdbData.metascore,
    genres: omdbData.genres.length > 0 ? omdbData.genres : null,
    countries: omdbData.countries.length > 0 ? omdbData.countries : null,
    director: omdbData.director,
    plot: omdbData.plot,
    posterUrl: omdbData.posterUrl,
    runtime: omdbData.runtime,
    awards: omdbData.awards,
    boxOffice: omdbData.boxOffice,
    ratings: omdbData.ratings.length > 0 ? omdbData.ratings : null,
  };

  // 1. Save manual mapping to Firestore
  try {
    let createdBy: string | null = null;
    try {
      const auth = getAuth();
      createdBy = auth.currentUser?.email || auth.currentUser?.uid || null;
    } catch {
      // Auth might not be initialized in test environments
    }

    await firestoreManualMappingAdapter.saveManualMapping({
      id: oldTitle.id,
      rawTitle: oldTitle.title,
      imdbId: newImdbId,
      parsedTitle: omdbData.title,
      parsedYear: omdbData.year,
      createdBy,
    });
  } catch (err: unknown) {
    const errStr = String(err);
    if (errStr.includes('permission-denied') || errStr.includes('Missing or insufficient permissions')) {
      throw new Error(
        'Missing or insufficient permissions за "manualMappings". Уверете се, че сте логнати с позволен (allowlisted) акаунт.'
      );
    }
    console.warn('Could not save manual mapping to Firestore:', err);
  }

  // 2. Trigger GitHub Actions scanner workflow immediately if PAT is configured
  try {
    await triggerGitHubScanner();
  } catch {
    // Ignore trigger failure if PAT not configured
  }

  return {
    ...oldTitle,
    ...updatedTitleData,
    id: newTitleId,
    firstSeenAt: oldTitle.firstSeenAt,
    lastSeenAt: oldTitle.lastSeenAt,
    updatedAt: now,
  };
};

export const triggerGitHubScanner = async (): Promise<boolean> => {
  try {
    const owner = typeof localStorage !== 'undefined' ? localStorage.getItem('movies_feed_gh_owner') || import.meta.env.VITE_GITHUB_OWNER || '' : '';
    const repo = typeof localStorage !== 'undefined' ? localStorage.getItem('movies_feed_gh_repo') || import.meta.env.VITE_GITHUB_REPO || 'movies-feed' : 'movies-feed';
    const pat = typeof localStorage !== 'undefined' ? localStorage.getItem('movies_feed_gh_pat') || import.meta.env.VITE_GITHUB_PAT || '' : '';
    const workflow = typeof localStorage !== 'undefined' ? localStorage.getItem('movies_feed_gh_workflow') || 'scanner.yml' : 'scanner.yml';
    const ref = typeof localStorage !== 'undefined' ? localStorage.getItem('movies_feed_gh_ref') || 'main' : 'main';

    if (!owner || !repo || !pat) {
      return false;
    }

    const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${pat}`,
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ref,
        inputs: {
          dry_run: false,
          force_days: '0',
        },
      }),
    });

    return response.status === 204 || response.ok;
  } catch (err) {
    console.warn('Failed to trigger GitHub Actions scanner:', err);
    return false;
  }
};
