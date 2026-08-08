import { Title, Occurrence } from '../domain/catalog';
import { getDb } from './firebaseApp';
import { doc, getDocs, collection, writeBatch, Timestamp, getDoc } from 'firebase/firestore';

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
  // 1. Fetch
  const omdbData = await fetchFromOmdb(imdbId, apiKey);
  const newImdbId = omdbData.imdbId || imdbId;
  
  // 2. Determine new ID
  let newTitleId = newImdbId.toLowerCase();
  
  // 3. Prepare updated title object
  const now = new Date();
  const updatedTitleData: any = {
    title: omdbData.title,
    normalizedTitle: normalizeTitleForId(omdbData.title),
    year: omdbData.year,
    mediaType: omdbData.mediaType,
    updatedAt: Timestamp.fromDate(now),
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
  
  // Clean up undefined fields
  Object.keys(updatedTitleData).forEach(key => {
    if (updatedTitleData[key] === undefined) {
      updatedTitleData[key] = null;
    }
  });

  const db = getDb();
  const batch = writeBatch(db);

  let finalFirstSeenAt = oldTitle.firstSeenAt;
  let finalLastSeenAt = oldTitle.lastSeenAt;

  if (newTitleId === oldTitle.id) {
    // Just update the existing document
    const titleRef = doc(db, 'titles', oldTitle.id);
    batch.update(titleRef, updatedTitleData);
  } else {
    // Create new title doc, migrate occurrences, delete old title doc
    const newTitleRef = doc(db, 'titles', newTitleId);
    
    // Check if new title doc already exists
    const existingNewDoc = await getDoc(newTitleRef);
    
    if (existingNewDoc.exists()) {
      const data = existingNewDoc.data();
      const existingFirstSeenAt = data.firstSeenAt?.toDate() || new Date();
      const existingLastSeenAt = data.lastSeenAt?.toDate() || new Date();
      if (existingFirstSeenAt < finalFirstSeenAt) finalFirstSeenAt = existingFirstSeenAt;
      if (existingLastSeenAt > finalLastSeenAt) finalLastSeenAt = existingLastSeenAt;
    }
    
    batch.set(newTitleRef, {
      ...updatedTitleData,
      firstSeenAt: Timestamp.fromDate(finalFirstSeenAt),
      lastSeenAt: Timestamp.fromDate(finalLastSeenAt),
    }, { merge: true });

    // Fetch and move occurrences
    const occurrencesSnap = await getDocs(collection(db, `titles/${oldTitle.id}/occurrences`));
    occurrencesSnap.forEach((occDoc) => {
      const newOccRef = doc(db, `titles/${newTitleId}/occurrences`, occDoc.id);
      batch.set(newOccRef, occDoc.data(), { merge: true });
      batch.delete(occDoc.ref);
    });

    // Delete old title doc
    batch.delete(doc(db, 'titles', oldTitle.id));
  }

  // Write omdbCache entry so backend doesn't overwrite it
  const cacheKey = await getCacheKey(oldTitle.title, oldTitle.year);
  const cacheRef = doc(db, 'omdbCache', cacheKey);
  const expiresAt = new Date();
  expiresAt.setDate(expiresAt.getDate() + 30);
  
  batch.set(cacheRef, {
    lookupTitle: oldTitle.title,
    lookupYear: oldTitle.year,
    status: 'found',
    payload: omdbData.rawPayload,
    fetchedAt: Timestamp.fromDate(now),
    expiresAt: Timestamp.fromDate(expiresAt),
  }, { merge: true });

  await batch.commit();

  return {
    ...oldTitle,
    ...updatedTitleData,
    id: newTitleId,
    firstSeenAt: finalFirstSeenAt,
    lastSeenAt: finalLastSeenAt,
    updatedAt: now,
  };
};
