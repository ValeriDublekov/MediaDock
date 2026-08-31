import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as firestoreModule from 'firebase/firestore';
import { FirestoreSettingsAdapter } from '../adapters/firestoreSettingsAdapter';
import {
  GlobalSettings,
  MAX_SETTINGS_FEEDS,
  MAX_SETTINGS_IMDB_VOTES,
  MAX_SETTINGS_LIST_ITEMS,
  MAX_SETTINGS_TEXT_LENGTH,
  MAX_SETTINGS_URL_LENGTH,
} from '../domain/settings';

vi.mock('firebase/firestore', () => ({
  doc: vi.fn((db, ...pathSegments) => ({ db, path: pathSegments.join('/') })),
  getDoc: vi.fn(),
  setDoc: vi.fn(),
}));

vi.mock('../adapters/firebaseApp', () => ({
  getDb: vi.fn(),
}));

const validSettings = (): GlobalSettings => ({
  rssFeeds: {
    Movies: { url: 'https://feed.example.test/movies.atom', type: 'movie' },
  },
  excludedGenres: ['Horror'],
  excludedCountries: ['India'],
  minMovieRating: 6.5,
  minSeriesRating: 7,
  minImdbVotes: 1000,
});

describe('FirestoreSettingsAdapter', () => {
  let adapter: FirestoreSettingsAdapter;
  const mockDb = { type: 'db' };

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = new FirestoreSettingsAdapter(() => mockDb as never);
  });

  it.each([
    ['extra settings field', () => ({ ...validSettings(), extra: true })],
    ['too many feeds', () => ({
      ...validSettings(),
      rssFeeds: Object.fromEntries(Array.from({ length: MAX_SETTINGS_FEEDS + 1 }, (_, index) => [
        `Feed ${index}`,
        { url: `https://feed.example.test/${index}.atom`, type: 'movie' },
      ])),
    })],
    ['empty feed name', () => ({ ...validSettings(), rssFeeds: { ' ': validSettings().rssFeeds.Movies } })],
    ['overlong feed name', () => ({ ...validSettings(), rssFeeds: { ['n'.repeat(MAX_SETTINGS_TEXT_LENGTH + 1)]: validSettings().rssFeeds.Movies } })],
    ['non-HTTPS URL', () => ({ ...validSettings(), rssFeeds: { Movies: { url: 'http://feed.example.test/movies.atom', type: 'movie' } } })],
    ['overlong URL', () => ({ ...validSettings(), rssFeeds: { Movies: { url: `https://${'a'.repeat(MAX_SETTINGS_URL_LENGTH)}`, type: 'movie' } } })],
    ['unsupported feed type', () => ({ ...validSettings(), rssFeeds: { Movies: { url: 'https://feed.example.test/movies.atom', type: 'documentary' } } })],
    ['extra feed field', () => ({ ...validSettings(), rssFeeds: { Movies: { ...validSettings().rssFeeds.Movies, enabled: true } } })],
    ['too many exclusions', () => ({ ...validSettings(), excludedGenres: Array(MAX_SETTINGS_LIST_ITEMS + 1).fill('Drama') })],
    ['invalid exclusion', () => ({ ...validSettings(), excludedCountries: [' '] })],
    ['overlong exclusion', () => ({ ...validSettings(), excludedGenres: ['g'.repeat(MAX_SETTINGS_TEXT_LENGTH + 1)] })],
    ['rating outside range', () => ({ ...validSettings(), minMovieRating: 11 })],
    ['non-finite rating', () => ({ ...validSettings(), minSeriesRating: Number.NaN })],
    ['non-integer votes', () => ({ ...validSettings(), minImdbVotes: 1.5 })],
    ['votes outside range', () => ({ ...validSettings(), minImdbVotes: MAX_SETTINGS_IMDB_VOTES + 1 })],
  ])('rejects %s before writing', async (_name, makeSettings) => {
    await expect(adapter.saveSettings(makeSettings() as GlobalSettings)).rejects.toThrow(
      'Scanner settings are invalid. Review the settings and try again.',
    );

    expect(firestoreModule.setDoc).not.toHaveBeenCalled();
  });

  it('rejects valid browser writes until a server-side control plane exists', async () => {
    const settings = validSettings();

    await expect(adapter.saveSettings(settings)).rejects.toThrow(
      'Scanner settings are read-only in the browser and must be updated server-side.',
    );

    expect(firestoreModule.setDoc).not.toHaveBeenCalled();
  });
});