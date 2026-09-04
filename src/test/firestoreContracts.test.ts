import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  FirestoreDocumentData,
  mapOccurrenceDocument,
  mapRssSnapshotItemDocument,
  mapRssSnapshotStateDocument,
  mapTitleDocument,
} from '../adapters/firestoreCatalogMappers';

function loadFixture(name: string): FirestoreDocumentData {
  return JSON.parse(
    readFileSync(resolve(process.cwd(), 'test-contracts', 'firestore', 'v1', name), 'utf8')
  ) as FirestoreDocumentData;
}

function normalizeTimestamps(
  document: FirestoreDocumentData,
  ...timestampFields: string[]
): FirestoreDocumentData {
  const normalized = { ...document };
  timestampFields.forEach((fieldName) => {
    const value = normalized[fieldName];
    normalized[fieldName] = {
      toDate: () => new Date(value as string),
    };
  });
  return normalized;
}

describe('Firestore cross-language contracts', () => {
  it('maps the shared title fixture to the public Title shape', () => {
    const fixture = loadFixture('title.json');

    expect(
      mapTitleDocument(
        'tt1234567',
        normalizeTimestamps(fixture, 'firstSeenAt', 'lastSeenAt', 'updatedAt')
      )
    ).toEqual({
      id: 'tt1234567',
      title: 'Example Film',
      normalizedTitle: 'example film',
      year: 2026,
      mediaType: 'movie',
      firstSeenAt: new Date('2026-08-07T10:00:00.000Z'),
      lastSeenAt: new Date('2026-08-08T10:00:00.000Z'),
      updatedAt: new Date('2026-08-08T11:00:00.000Z'),
      imdbId: 'tt1234567',
      imdbRating: 8.2,
      imdbVotes: 1200,
      metascore: 74,
      genres: ['Drama', 'Mystery'],
      countries: ['US'],
      director: 'Example Director',
      plot: 'A researcher follows a difficult lead.',
      posterUrl: 'https://example.test/posters/example-film.jpg',
      runtime: '110 min',
      awards: 'Festival selection',
      boxOffice: '$1,000,000',
      ratings: [
        {
          Source: 'Internet Movie Database',
          Value: '8.2/10',
        },
      ],
    });
  });

  it('maps the shared occurrence fixture to the public Occurrence shape', () => {
    const fixture = loadFixture('occurrence.json');

    expect(
      mapOccurrenceDocument(
        'occurrence-1',
        normalizeTimestamps(fixture, 'firstSeenAt', 'lastSeenAt')
      )
    ).toEqual({
      id: 'occurrence-1',
      sourceFeedId: 'feed-movies',
      sourceFeedName: 'Movies Feed',
      feedEntryId: 'entry-2026-08-07',
      torrentUrl: 'https://example.test/torrents/example-film',
      rawTitle: 'Example Film 2026 1080p',
      quality: '1080p',
      ripType: 'WEB-DL',
      firstSeenAt: new Date('2026-08-07T10:00:00.000Z'),
      lastSeenAt: new Date('2026-08-08T10:00:00.000Z'),
    });
  });

  it('maps the shared snapshot state fixture and normalizes its timestamp', () => {
    const fixture = loadFixture('rss-snapshot-state.json');
    const state = mapRssSnapshotStateDocument(
      normalizeTimestamps(fixture, 'createdAt')
    );

    expect(state).toEqual({
      snapshotId: 'snapshot-run-2026-08-07',
      runId: 'run-2026-08-07',
      createdAt: new Date('2026-08-08T11:00:00.000Z'),
      itemCount: 2,
    });
  });

  it('maps every required snapshot ordering field', () => {
    const fixture = loadFixture('rss-snapshot-item.json');

    expect(mapRssSnapshotItemDocument(fixture)).toEqual({
      titleId: 'tt1234567',
      sourceType: 'movie',
      groupOrder: 0,
      feedOrder: 1,
      entryOrder: 2,
      rssPosition: 0,
    });
  });

  it('fails explicitly when a required snapshot ordering field is missing', () => {
    const fixture = loadFixture('rss-snapshot-item.json');

    for (const fieldName of ['groupOrder', 'feedOrder', 'entryOrder', 'rssPosition']) {
      const invalidFixture = { ...fixture };
      delete invalidFixture[fieldName];

      expect(() => mapRssSnapshotItemDocument(invalidFixture)).toThrow(
        `RSS snapshot item is missing a numeric ${fieldName}`
      );
    }
  });
});
