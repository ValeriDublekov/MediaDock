import { useState, useEffect, useCallback, useRef } from 'react';
import { Title, CatalogCursor, CatalogRepository } from '../domain/catalog';
import { firestoreCatalogAdapter } from '../adapters/firestoreCatalogAdapter';

export interface UseCatalogOptions {
  repository?: CatalogRepository;
  pageSize?: number;
  autoFetch?: boolean;
}

export interface UseCatalogReturn {
  titles: Title[];
  isLoading: boolean;
  isLoadingMore: boolean;
  error: Error | null;
  hasMore: boolean;
  nextCursor: CatalogCursor | null;
  isEmpty: boolean;
  loadInitialPage: () => Promise<void>;
  loadNextPage: () => Promise<void>;
  retry: () => Promise<void>;
}

export function useCatalog(options: UseCatalogOptions = {}): UseCatalogReturn {
  const {
    repository = firestoreCatalogAdapter,
    pageSize = 10,
    autoFetch = true,
  } = options;

  const [titles, setTitles] = useState<Title[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isLoadingMore, setIsLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const [hasMore, setHasMore] = useState<boolean>(false);
  const [nextCursor, setNextCursor] = useState<CatalogCursor | null>(null);

  const repoRef = useRef(repository);
  repoRef.current = repository;

  const lastFailedActionRef = useRef<'initial' | 'next' | null>(null);

  const loadInitialPage = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    lastFailedActionRef.current = null;

    try {
      const page = await repoRef.current.getCatalogPage({
        pageSize,
        cursor: null,
      });

      setTitles(page.items);
      setHasMore(page.hasMore);
      setNextCursor(page.nextCursor);
    } catch (err) {
      const errorObj = err instanceof Error ? err : new Error(String(err));
      setError(errorObj);
      lastFailedActionRef.current = 'initial';
    } finally {
      setIsLoading(false);
    }
  }, [pageSize]);

  const loadNextPage = useCallback(async () => {
    if (isLoading || isLoadingMore || !hasMore || !nextCursor) {
      return;
    }

    setIsLoadingMore(true);
    setError(null);
    lastFailedActionRef.current = null;

    try {
      const page = await repoRef.current.getCatalogPage({
        pageSize,
        cursor: nextCursor,
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
  }, [isLoading, isLoadingMore, hasMore, nextCursor, pageSize]);

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
    isEmpty,
    loadInitialPage,
    loadNextPage,
    retry,
  };
}
