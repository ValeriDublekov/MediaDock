export interface ParseLog {
  id: string;
  rawTitle: string;
  feedName: string;
  parsedSuccessfully: boolean;
  parsedTitle: string | null;
  parsedYear: number | null;
  omdbStatus: string; // 'found' | 'not_found' | 'skipped' | 'error' | 'not_parsed'
  ignored: boolean;
  ignoreReason: string | null; // 'no_title' | 'omdb_not_found' | 'excluded_country_or_genre' | 'omdb_limit_reached' | 'omdb_error' | 'empty_title' | 'parse_only' | null
  processedAt: Date;
}

export interface ParseLogRepository {
  getRecentParseLogs(limitCount?: number): Promise<ParseLog[]>;
}
