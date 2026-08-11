export type UserTitleStatus = 'favorite' | 'ignored';

export interface UserTitleEntry {
  titleId: string;
  status: UserTitleStatus;
  updatedAt: Date;
}

export interface UserDataRepository {
  getUserTitles(userId: string): Promise<Record<string, UserTitleStatus>>;
  subscribeUserTitles(
    userId: string,
    callback: (userTitles: Record<string, UserTitleStatus>) => void
  ): () => void;
  setUserTitleStatus(
    userId: string,
    titleId: string,
    status: UserTitleStatus | null
  ): Promise<void>;
}
