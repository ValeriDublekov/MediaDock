/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

export interface RssFeedConfig {
  url: string;
  type: 'movie' | 'series' | string;
}

export interface GlobalSettings {
  rssFeeds: Record<string, RssFeedConfig>;
  excludedGenres: string[];
  excludedCountries: string[];
  minMovieRating: number;
  minSeriesRating: number;
  minImdbVotes: number;
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
