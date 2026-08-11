import { useState, useEffect, useCallback, useMemo } from 'react';
import { UserTitleStatus, UserDataRepository } from '../domain/userData';
import { firestoreUserDataAdapter } from '../adapters/firestoreUserDataAdapter';
import { useAuth } from './AuthContext';

export interface UseUserTitlesOptions {
  repository?: UserDataRepository;
  userId?: string;
}

export interface UseUserTitlesReturn {
  userTitles: Record<string, UserTitleStatus>;
  isLoading: boolean;
  toggleFavorite: (titleId: string) => Promise<void>;
  toggleIgnored: (titleId: string) => Promise<void>;
  setStatus: (titleId: string, status: UserTitleStatus | null) => Promise<void>;
  isFavorite: (titleId: string) => boolean;
  isIgnored: (titleId: string) => boolean;
  favoriteTitleIds: string[];
  ignoredTitleIds: string[];
}

export function useUserTitles(options: UseUserTitlesOptions = {}): UseUserTitlesReturn {
  let user = null;
  try {
    const auth = useAuth();
    user = auth?.user ?? null;
  } catch {
    // Outside AuthProvider context
  }

  const repository = options.repository || firestoreUserDataAdapter;
  const targetUserId = options.userId || user?.uid;

  const [userTitles, setUserTitles] = useState<Record<string, UserTitleStatus>>({});
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    if (!targetUserId) {
      setUserTitles({});
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    const unsubscribe = repository.subscribeUserTitles(targetUserId, (titles) => {
      setUserTitles(titles);
      setIsLoading(false);
    });

    return () => {
      unsubscribe();
    };
  }, [targetUserId, repository]);

  const setStatus = useCallback(
    async (titleId: string, status: UserTitleStatus | null) => {
      if (!targetUserId) return;
      // Optimistic update
      setUserTitles((prev) => {
        const next = { ...prev };
        if (status === null) {
          delete next[titleId];
        } else {
          next[titleId] = status;
        }
        return next;
      });

      try {
        await repository.setUserTitleStatus(targetUserId, titleId, status);
      } catch (err) {
        console.error('Failed to set title status:', err);
      }
    },
    [targetUserId, repository]
  );

  const toggleFavorite = useCallback(
    async (titleId: string) => {
      const current = userTitles[titleId];
      if (current === 'favorite') {
        await setStatus(titleId, null);
      } else {
        await setStatus(titleId, 'favorite');
      }
    },
    [userTitles, setStatus]
  );

  const toggleIgnored = useCallback(
    async (titleId: string) => {
      const current = userTitles[titleId];
      if (current === 'ignored') {
        await setStatus(titleId, null);
      } else {
        await setStatus(titleId, 'ignored');
      }
    },
    [userTitles, setStatus]
  );

  const isFavorite = useCallback(
    (titleId: string) => userTitles[titleId] === 'favorite',
    [userTitles]
  );

  const isIgnored = useCallback(
    (titleId: string) => userTitles[titleId] === 'ignored',
    [userTitles]
  );

  const favoriteTitleIds = useMemo(() => {
    return Object.keys(userTitles).filter((id) => userTitles[id] === 'favorite');
  }, [userTitles]);

  const ignoredTitleIds = useMemo(() => {
    return Object.keys(userTitles).filter((id) => userTitles[id] === 'ignored');
  }, [userTitles]);

  return {
    userTitles,
    isLoading,
    toggleFavorite,
    toggleIgnored,
    setStatus,
    isFavorite,
    isIgnored,
    favoriteTitleIds,
    ignoredTitleIds,
  };
}
