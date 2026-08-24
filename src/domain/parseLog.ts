export interface ParseTraceDetails {
  parsedTitle?: string | null;
  parsedYear?: number | null;
  parsedQuality?: string | null;
  parsedRipType?: string | null;
  parsedIsSeries?: boolean;
  feedName?: string | null;
  feedType?: string | null;
  cacheKey?: string | null;
  cacheHit?: boolean;
  cacheStatus?: string | null;
  cacheFetchedAt?: string | null;
  omdbQueryTitle?: string | null;
  omdbQueryYear?: number | null;
  omdbQueryType?: string | null;
  omdbFoundTitle?: string | null;
  omdbFoundYear?: number | null;
  omdbFoundType?: string | null;
  omdbImdbId?: string | null;
  omdbGenres?: string[];
  omdbCountries?: string[];
  omdbRating?: number | null;
  decision?: string | null;
  decisionDetails?: string | null;
  [key: string]: unknown;
}

export interface ParseLog {
  id: string;
  rawTitle: string;
  feedName: string;
  parsedSuccessfully: boolean;
  parsedTitle: string | null;
  parsedYear: number | null;
  omdbStatus: string; // 'found' | 'not_found' | 'skipped' | 'error' | 'not_parsed'
  ignored: boolean;
  ignoreReason: string | null; // 'no_title' | 'parse_error' | 'entry_error' | 'omdb_not_found' | 'excluded_country_or_genre' | 'omdb_limit_reached' | 'omdb_error' | 'empty_title' | 'parse_only' | 'media_type_mismatch' | 'year_mismatch' | 'ai_rejected' | null
  errorMessage?: string | null;
  traceDetails?: ParseTraceDetails | null;
  processedAt: Date;
}

export interface ParseLogRepository {
  getRecentParseLogs(limitCount?: number): Promise<ParseLog[]>;
}
