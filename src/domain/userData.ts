/**
 * Interface extension point for future owner-scoped user data write operations
 * (e.g., user favorites, watch history, bookmarks).
 *
 * Requirements & Constraints:
 * - Explicit interface definition for future owner-scoped user operations.
 * - Must NOT include write UI, writable schema, or placeholder write calls in the current scope.
 */
export interface UserDataWriteRepository {
  // Reserved extension point for future owner-scoped write methods
  // e.g., setFavorite(userId: string, titleId: string, isFavorite: boolean): Promise<void>;
}
