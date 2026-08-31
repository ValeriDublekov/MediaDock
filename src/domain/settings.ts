/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

export interface RssFeedConfig {
  url: string;
  type: 'movie' | 'series';
}

export const MAX_SETTINGS_FEEDS = 20;
export const MAX_SETTINGS_LIST_ITEMS = 100;
export const MAX_SETTINGS_TEXT_LENGTH = 500;
export const MAX_SETTINGS_URL_LENGTH = 2048;
export const MAX_SETTINGS_RATING = 10;
export const MAX_SETTINGS_IMDB_VOTES = 1_000_000_000;

export interface GlobalSettings {
  rssFeeds: Record<string, RssFeedConfig>;
  excludedGenres: string[];
  excludedCountries: string[];
  minMovieRating: number;
  minSeriesRating: number;
  minImdbVotes: number;
}

const SETTINGS_FIELDS = [
  'rssFeeds',
  'excludedGenres',
  'excludedCountries',
  'minMovieRating',
  'minSeriesRating',
  'minImdbVotes',
] as const;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasExactFields(value: Record<string, unknown>, fields: readonly string[]): boolean {
  const keys = Object.keys(value);
  return keys.length === fields.length && fields.every((field) => keys.includes(field));
}

function isBoundedText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= MAX_SETTINGS_TEXT_LENGTH;
}

function isHttpsUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_SETTINGS_URL_LENGTH) {
    return false;
  }

  try {
    return new URL(value).protocol === 'https:';
  } catch {
    return false;
  }
}

function isExclusionList(value: unknown): value is string[] {
  return Array.isArray(value)
    && value.length <= MAX_SETTINGS_LIST_ITEMS
    && value.every(isBoundedText);
}

function isRating(value: unknown): value is number {
  return typeof value === 'number'
    && Number.isFinite(value)
    && value >= 0
    && value <= MAX_SETTINGS_RATING;
}

export function isValidSettings(value: unknown): value is GlobalSettings {
  if (!isObject(value) || !hasExactFields(value, SETTINGS_FIELDS)) {
    return false;
  }

  const feeds = value.rssFeeds;
  if (!isObject(feeds) || Object.keys(feeds).length > MAX_SETTINGS_FEEDS) {
    return false;
  }

  const validFeeds = Object.entries(feeds).every(([name, feed]) =>
    isBoundedText(name)
    && isObject(feed)
    && hasExactFields(feed, ['url', 'type'])
    && isHttpsUrl(feed.url)
    && (feed.type === 'movie' || feed.type === 'series')
  );

  return validFeeds
    && isExclusionList(value.excludedGenres)
    && isExclusionList(value.excludedCountries)
    && isRating(value.minMovieRating)
    && isRating(value.minSeriesRating)
    && typeof value.minImdbVotes === 'number'
    && Number.isInteger(value.minImdbVotes)
    && value.minImdbVotes >= 0
    && value.minImdbVotes <= MAX_SETTINGS_IMDB_VOTES;
}

export const DEFAULT_SETTINGS: GlobalSettings = {
  rssFeeds: {
    "Movies (HD)": {
      url: "https://feed.rutracker.cc/atom/f/313.atom",
      type: "movie"
    },
    "Series (HD)": {
      url: "https://feed.rutracker.cc/atom/f/2366.atom",
      type: "series"
    },
    "New Series / Episodes": {
      url: "https://feed.rutracker.cc/atom/f/1803.atom",
      type: "series"
    }
  },
  excludedGenres: ["Horror"],
  excludedCountries: ["India", "Turkey"],
  minMovieRating: 6.5,
  minSeriesRating: 7.0,
  minImdbVotes: 0
};

export interface SettingsRepository {
  getSettings(): Promise<GlobalSettings>;
  saveSettings(settings: GlobalSettings): Promise<void>;
}
