import { describe, it, expect, vi, beforeEach } from 'vitest';
import { FirestoreCatalogAdapter } from '../adapters/firestoreCatalogAdapter';
import * as firestoreModule from 'firebase/firestore';

vi.mock('firebase/firestore', () => {
  return {
    collection: vi.fn((db, ...pathSegments) => ({ _type: 'collection', path: pathSegments.join('/') })),
    doc: vi.fn((db, ...pathSegments) => ({ _type: 'doc', path: pathSegments.join('/') })),
    getDoc: vi.fn(),
    getDocs: vi.fn(),
    query: vi.fn((ref, ...constraints) => ({ _type: 'query', ref, constraints })),
    orderBy: vi.fn((field, dir) => ({ type: 'orderBy', field, dir })),
    limit: vi.fn((count) => ({ type: 'limit', count })),
    startAfter: vi.fn((...args) => ({ type: 'startAfter', args })),
    documentId: vi.fn(() => '__name__'),
    where: vi.fn((field, op, value) => ({ type: 'where', field, op, value })),
    Timestamp: {
      fromDate: vi.fn((date: Date) => ({
        toDate: () => date,
        seconds: Math.floor(date.getTime() / 1000),
      })),
    },
  };
});

describe('FirestoreCatalogAdapter', () => {
  let adapter: FirestoreCatalogAdapter;
  let mockDb: any;

  beforeEach(() => {
    vi.clearAllMocks();
    mockDb = { _type: 'db' };
    adapter = new FirestoreCatalogAdapter(() => mockDb);
  });

  it('getCatalogPage queries titles without cursor and maps domain models', async () => {
    const mockDate = new Date('2026-08-01T10:00:00Z');
    const mockDocs = [
      {
        id: 'tt001',
        data: () => ({
          title: 'Test Movie',
          normalizedTitle: 'test movie',
          year: 2024,
          mediaType: 'movie',
          firstSeenAt: { toDate: () => mockDate },
          lastSeenAt: { toDate: () => mockDate },
          updatedAt: { toDate: () => mockDate },
          imdbId: 'tt001',
          imdbRating: 8.5,
          genres: ['Action', 'Sci-Fi'],
        }),
      },
    ];

    vi.mocked(firestoreModule.getDocs).mockResolvedValueOnce({ docs: mockDocs } as any);

    const result = await adapter.getCatalogPage({ pageSize: 10 });

    expect(firestoreModule.collection).toHaveBeenCalledWith(mockDb, 'titles');
    expect(firestoreModule.orderBy).toHaveBeenCalledWith('lastSeenAt', 'desc');
    expect(firestoreModule.orderBy).toHaveBeenCalledWith('__name__', 'desc');
    expect(firestoreModule.limit).toHaveBeenCalledWith(10);
    expect(result.items).toHaveLength(1);
    expect(result.items[0]).toEqual({
      id: 'tt001',
      title: 'Test Movie',
      normalizedTitle: 'test movie',
      year: 2024,
      mediaType: 'movie',
      firstSeenAt: mockDate,
      lastSeenAt: mockDate,
      updatedAt: mockDate,
      imdbId: 'tt001',
      imdbRating: 8.5,
      imdbVotes: null,
      metascore: null,
      genres: ['Action', 'Sci-Fi'],
      countries: null,
      director: null,
      plot: null,
      posterUrl: null,
      runtime: null,
      awards: null,
      boxOffice: null,
      ratings: null,
    });
    expect(result.hasMore).toBe(false);
    expect(result.nextCursor).toBeNull();
  });

  it('getCatalogPage uses a bounded historical query when no cursor is provided', async () => {
    const mockDate = new Date('2026-08-07T10:00:00Z');
    const mockDocs = [
      {
        id: 'tt002',
        data: () => ({
          title: 'Recent Movie',
          normalizedTitle: 'recent movie',
          year: 2026,
          mediaType: 'movie',
          firstSeenAt: { toDate: () => mockDate },
          lastSeenAt: { toDate: () => mockDate },
          updatedAt: { toDate: () => mockDate },
        }),
      },
    ];

    vi.mocked(firestoreModule.getDocs).mockResolvedValueOnce({
      docs: mockDocs,
    } as any);

    const result = await adapter.getCatalogPage({ pageSize: 10 });

    expect(firestoreModule.collection).toHaveBeenCalledWith(mockDb, 'titles');
    expect(firestoreModule.orderBy).toHaveBeenCalledWith('lastSeenAt', 'desc');
    expect(firestoreModule.orderBy).toHaveBeenCalledWith('__name__', 'desc');
    expect(firestoreModule.limit).toHaveBeenCalledWith(10);
    expect(result.items).toHaveLength(1);
    expect(result.items[0].title).toBe('Recent Movie');
    expect(result.hasMore).toBe(false);
    expect(result.nextCursor).toBeNull();
  });

  it('getCatalogPage passes cursor and computes nextCursor when page is full', async () => {
    const mockDate1 = new Date('2026-08-01T10:00:00Z');
    const mockDate2 = new Date('2026-07-31T10:00:00Z');
    const mockDocs = [
      {
        id: 'tt001',
        data: () => ({
          title: 'Movie 1',
          lastSeenAt: { toDate: () => mockDate1 },
          firstSeenAt: { toDate: () => mockDate1 },
        }),
      },
      {
        id: 'tt002',
        data: () => ({
          title: 'Movie 2',
          lastSeenAt: { toDate: () => mockDate2 },
          firstSeenAt: { toDate: () => mockDate2 },
        }),
      },
    ];

    vi.mocked(firestoreModule.getDocs).mockResolvedValueOnce({
      docs: mockDocs,
    } as any);

    const cursorDate = new Date('2026-08-02T10:00:00Z');
    const result = await adapter.getCatalogPage({
      pageSize: 2,
      cursor: { lastSeenAt: cursorDate, id: 'tt000' },
    });

    expect(firestoreModule.startAfter).toHaveBeenCalled();
    expect(result.hasMore).toBe(true);
    expect(result.nextCursor).toEqual({
      lastSeenAt: mockDate2,
      id: 'tt002',
    });
  });

  it('getTitleById returns mapped Title when document exists', async () => {
    const mockDate = new Date('2026-08-01T10:00:00Z');
    vi.mocked(firestoreModule.getDoc).mockResolvedValueOnce({
      exists: () => true,
      id: 'tt123',
      data: () => ({
        title: 'Single Movie',
        normalizedTitle: 'single movie',
        year: 2023,
        mediaType: 'movie',
        firstSeenAt: { toDate: () => mockDate },
        lastSeenAt: { toDate: () => mockDate },
        updatedAt: { toDate: () => mockDate },
      }),
    } as any);

    const title = await adapter.getTitleById('tt123');

    expect(firestoreModule.doc).toHaveBeenCalledWith(mockDb, 'titles', 'tt123');
    expect(title).not.toBeNull();
    expect(title?.id).toBe('tt123');
    expect(title?.title).toBe('Single Movie');
  });

  it('getLatestRssSnapshotPage hydrates titles in snapshot order', async () => {
    const mockDate = new Date('2026-08-01T10:00:00Z');
    const snapshotItems = [
      {
        id: 'tt001',
        data: () => ({
          titleId: 'tt001',
          sourceType: 'movie',
          groupOrder: 0,
          feedOrder: 0,
          entryOrder: 0,
          rssPosition: 0,
        }),
      },
      {
        id: 'tt002',
        data: () => ({
          titleId: 'tt002',
          sourceType: 'series',
          groupOrder: 1,
          feedOrder: 0,
          entryOrder: 1,
          rssPosition: 1,
        }),
      },
      {
        id: 'tt003',
        data: () => ({
          titleId: 'tt003',
          sourceType: 'movie',
          groupOrder: 0,
          feedOrder: 1,
          entryOrder: 0,
          rssPosition: 2,
        }),
      },
    ];
    const titleDocs = [
      {
        id: 'tt002',
        data: () => ({
          title: 'Series Two',
          normalizedTitle: 'series two',
          year: 2023,
          mediaType: 'series',
          firstSeenAt: { toDate: () => mockDate },
          lastSeenAt: { toDate: () => mockDate },
          updatedAt: { toDate: () => mockDate },
        }),
      },
      {
        id: 'tt001',
        data: () => ({
          title: 'Movie One',
          normalizedTitle: 'movie one',
          year: 2024,
          mediaType: 'movie',
          firstSeenAt: { toDate: () => mockDate },
          lastSeenAt: { toDate: () => mockDate },
          updatedAt: { toDate: () => mockDate },
        }),
      },
    ];

    vi.mocked(firestoreModule.getDoc).mockResolvedValueOnce({
      exists: () => true,
      data: () => ({ snapshotId: 'snapshot-1' }),
    } as any);
    vi.mocked(firestoreModule.getDocs)
      .mockResolvedValueOnce({ docs: snapshotItems } as any)
      .mockResolvedValueOnce({ docs: titleDocs } as any);

    const result = await adapter.getLatestRssSnapshotPage({
      pageSize: 2,
      sourceType: 'movie',
    });

    expect(firestoreModule.collection).toHaveBeenCalledWith(
      mockDb,
      'rssSnapshots',
      'snapshot-1',
      'items'
    );
    expect(firestoreModule.where).toHaveBeenCalledWith('sourceType', '==', 'movie');
    expect(firestoreModule.orderBy).toHaveBeenCalledWith('rssPosition', 'asc');
    expect(firestoreModule.limit).toHaveBeenCalledWith(3);
    expect(result.items.map((title) => title.id)).toEqual(['tt001', 'tt002']);
    expect(result.snapshotId).toBe('snapshot-1');
    expect(result.hasMore).toBe(true);
    expect(result.nextCursor).toEqual({
      snapshotId: 'snapshot-1',
      rssPosition: 1,
      titleId: 'tt002',
    });
  });

  it('getTitleById returns null when document does not exist', async () => {
    vi.mocked(firestoreModule.getDoc).mockResolvedValueOnce({
      exists: () => false,
    } as any);

    const title = await adapter.getTitleById('missing');

    expect(title).toBeNull();
  });

  it('getOccurrences queries titles/{titleId}/occurrences and maps domain models', async () => {
    const mockDate = new Date('2026-08-01T10:00:00Z');
    const mockDocs = [
      {
        id: 'occ001',
        data: () => ({
          sourceFeedId: 'feed1',
          sourceFeedName: 'Feed 1',
          feedEntryId: 'entry1',
          torrentUrl: 'https://example.com/torrent/1',
          rawTitle: 'Raw Title 1080p',
          quality: '1080p',
          ripType: 'BDRip',
          firstSeenAt: { toDate: () => mockDate },
          lastSeenAt: { toDate: () => mockDate },
        }),
      },
    ];

    vi.mocked(firestoreModule.getDocs).mockResolvedValueOnce({
      docs: mockDocs,
    } as any);

    const occurrences = await adapter.getOccurrences('tt123');

    expect(firestoreModule.collection).toHaveBeenCalledWith(mockDb, 'titles', 'tt123', 'occurrences');
    expect(firestoreModule.orderBy).toHaveBeenCalledWith('firstSeenAt', 'desc');
    expect(occurrences).toHaveLength(1);
    expect(occurrences[0]).toEqual({
      id: 'occ001',
      sourceFeedId: 'feed1',
      sourceFeedName: 'Feed 1',
      feedEntryId: 'entry1',
      torrentUrl: 'https://example.com/torrent/1',
      rawTitle: 'Raw Title 1080p',
      quality: '1080p',
      ripType: 'BDRip',
      firstSeenAt: mockDate,
      lastSeenAt: mockDate,
    });
  });
});
