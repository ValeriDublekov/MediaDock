import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Title,
  CatalogCursor,
  CatalogRepository,
  LatestRssSnapshotCursor,
} from '../domain/catalog';

export type CatalogDataSource = 'catalog' | 'latest';
import { firestoreCatalogAdapter } from '../adapters/firestoreCatalogAdapter';

export interface UseCatalogOptions {
  repository?: CatalogRepository;
  pageSize?: number;
  autoFetch?: boolean;
  source?: CatalogDataSource;
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

  const loadInitialPage = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    lastFailedActionRef.current = null;
    setLatestSnapshotAvailable(null);

    try {
      const repository = repoRef.current;
      const page =
        source === 'latest' && repository.getLatestRssSnapshotPage
          ? await repository.getLatestRssSnapshotPage({ pageSize, cursor: null })
          : await repository.getCatalogPage({ pageSize, cursor: null });

      setTitles(page.items);
      setHasMore(page.hasMore);
      setNextCursor(page.nextCursor);
      if (source === 'latest' && repository.getLatestRssSnapshotPage) {
        setLatestSnapshotAvailable(page.snapshotId !== null);
      }
    } catch (err) {
      const errorObj = err instanceof Error ? err : new Error(String(err));
      setError(errorObj);
      lastFailedActionRef.current = 'initial';
    } finally {
      setIsLoading(false);
    }
  }, [pageSize, source]);

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
  }, [isLoading, isLoadingMore, hasMore, nextCursor, pageSize, source]);

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
