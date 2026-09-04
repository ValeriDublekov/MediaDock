import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Title,
  CatalogCursor,
  CatalogRepository,
  LatestRssSnapshotCursor,
  RssSourceType,
} from '../domain/catalog';

export type CatalogDataSource = 'catalog' | 'latest';
import { firestoreCatalogAdapter } from '../adapters/firestoreCatalogAdapter';

export interface UseCatalogOptions {
  repository?: CatalogRepository;
  pageSize?: number;
  autoFetch?: boolean;
  source?: CatalogDataSource;
  rssSourceType?: RssSourceType;
}

export interface UseCatalogReturn {
  titles: Title[];
  isLoading: boolean;
  isLoadingMore: boolean;
  error: Error | null;
  hasMore: boolean;
  nextCursor: CatalogCursor | LatestRssSnapshotCursor | null;
  latestSnapshotAvailable: boolean | null;
  isEmpty: boolean;
  loadInitialPage: () => Promise<void>;
  loadNextPage: () => Promise<void>;
  retry: () => Promise<void>;
}

export function useCatalog(options: UseCatalogOptions = {}): UseCatalogReturn {
  const {
    repository = firestoreCatalogAdapter,
    pageSize = 16,
    autoFetch = true,
    source = 'catalog',
    rssSourceType = 'movie',
  } = options;

  const [titles, setTitles] = useState<Title[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isLoadingMore, setIsLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const [hasMore, setHasMore] = useState<boolean>(false);
  const [nextCursor, setNextCursor] = useState<CatalogCursor | LatestRssSnapshotCursor | null>(null);
  const [latestSnapshotAvailable, setLatestSnapshotAvailable] = useState<boolean | null>(null);

  const repoRef = useRef(repository);
  repoRef.current = repository;

  const lastFailedActionRef = useRef<'initial' | 'next' | null>(null);
  const requestIdRef = useRef(0);

  const loadInitialPage = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setIsLoading(true);
    setError(null);
    setTitles([]);
    setHasMore(false);
    setNextCursor(null);
    lastFailedActionRef.current = null;
    setLatestSnapshotAvailable(null);

    try {
      const repository = repoRef.current;
      if (source === 'latest' && repository.getLatestRssSnapshotPage) {
        const loadedTitles: Title[] = [];
        const loadedIds = new Set<string>();
        let cursor: LatestRssSnapshotCursor | null = null;
        let snapshotAvailable = false;

        do {
          const page = await repository.getLatestRssSnapshotPage({
            pageSize,
            sourceType: rssSourceType,
            cursor,
          });
          if (requestId !== requestIdRef.current) return;

          snapshotAvailable = page.snapshotId !== null;
          page.items.forEach((item) => {
            if (!loadedIds.has(item.id)) {
              loadedIds.add(item.id);
              loadedTitles.push(item);
            }
          });

          if (!page.hasMore || !page.nextCursor) break;
          if (
            cursor?.snapshotId === page.nextCursor.snapshotId &&
            cursor.rssPosition === page.nextCursor.rssPosition
          ) {
            throw new Error('RSS snapshot pagination did not advance');
          }
          cursor = page.nextCursor;
        } while (true);

        setTitles(loadedTitles);
        setLatestSnapshotAvailable(snapshotAvailable);
      } else {
        const page = await repository.getCatalogPage({ pageSize, cursor: null });
        if (requestId !== requestIdRef.current) return;
        setTitles(page.items);
        setHasMore(page.hasMore);
        setNextCursor(page.nextCursor);
      }
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      const errorObj = err instanceof Error ? err : new Error(String(err));
      setError(errorObj);
      lastFailedActionRef.current = 'initial';
    } finally {
      if (requestId === requestIdRef.current) setIsLoading(false);
    }
  }, [pageSize, rssSourceType, source]);

  const loadNextPage = useCallback(async () => {
    if (isLoading || isLoadingMore || !hasMore || !nextCursor) {
      return;
    }

    setIsLoadingMore(true);
    setError(null);
    lastFailedActionRef.current = null;

    try {
      const repository = repoRef.current;
      const page =
        source === 'latest' && repository.getLatestRssSnapshotPage
          ? await repository.getLatestRssSnapshotPage({
              pageSize,
              sourceType: rssSourceType,
              cursor: nextCursor as LatestRssSnapshotCursor,
            })
          : await repository.getCatalogPage({
              pageSize,
              cursor: nextCursor as CatalogCursor,
            });

      setTitles((prevTitles) => {
        // Suppress duplicate IDs when pages are merged
        const existingIds = new Set(prevTitles.map((item) => item.id));
        const uniqueNewItems = page.items.filter((item) => !existingIds.has(item.id));
        return [...prevTitles, ...uniqueNewItems];
      });

      setHasMore(page.hasMore);
      setNextCursor(page.nextCursor);
    } catch (err) {
      const errorObj = err instanceof Error ? err : new Error(String(err));
      setError(errorObj);
      lastFailedActionRef.current = 'next';
    } finally {
      setIsLoadingMore(false);
    }
  }, [isLoading, isLoadingMore, hasMore, nextCursor, pageSize, rssSourceType, source]);

  const retry = useCallback(async () => {
    if (lastFailedActionRef.current === 'next' && nextCursor) {
      await loadNextPage();
    } else {
      await loadInitialPage();
    }
  }, [loadInitialPage, loadNextPage, nextCursor]);

  useEffect(() => {
    if (autoFetch) {
      loadInitialPage();
    }
  }, [autoFetch, loadInitialPage]);

  const isEmpty = !isLoading && !error && titles.length === 0;

  return {
    titles,
    isLoading,
    isLoadingMore,
    error,
    hasMore,
    nextCursor,
    latestSnapshotAvailable,
    isEmpty,
    loadInitialPage,
    loadNextPage,
    retry,
  };
}
