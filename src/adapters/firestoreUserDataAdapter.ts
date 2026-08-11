import {
  collection,
  doc,
  getDocs,
  onSnapshot,
  setDoc,
  deleteDoc,
  serverTimestamp,
  Firestore,
} from 'firebase/firestore';
import { getDb } from './firebaseApp';
import { UserDataRepository, UserTitleStatus } from '../domain/userData';

export class FirestoreUserDataAdapter implements UserDataRepository {
  constructor(private getDbInstance: () => Firestore = getDb) {}

  async getUserTitles(userId: string): Promise<Record<string, UserTitleStatus>> {
    if (!userId) return {};
    const db = this.getDbInstance();
    const userTitlesRef = collection(db, 'users', userId, 'userTitles');
    const snapshot = await getDocs(userTitlesRef);
    const result: Record<string, UserTitleStatus> = {};
    snapshot.forEach((docSnap) => {
      const data = docSnap.data();
      if (data.status === 'favorite' || data.status === 'ignored') {
        result[docSnap.id] = data.status;
      }
    });
    return result;
  }

  subscribeUserTitles(
    userId: string,
    callback: (userTitles: Record<string, UserTitleStatus>) => void
  ): () => void {
    if (!userId) {
      callback({});
      return () => {};
    }
    const db = this.getDbInstance();
    const userTitlesRef = collection(db, 'users', userId, 'userTitles');
    const unsubscribe = onSnapshot(
      userTitlesRef,
      (snapshot) => {
        const result: Record<string, UserTitleStatus> = {};
        snapshot.forEach((docSnap) => {
          const data = docSnap.data();
          if (data.status === 'favorite' || data.status === 'ignored') {
            result[docSnap.id] = data.status;
          }
        });
        callback(result);
      },
      (err) => {
        console.error('Error listening to userTitles:', err);
      }
    );
    return unsubscribe;
  }

  async setUserTitleStatus(
    userId: string,
    titleId: string,
    status: UserTitleStatus | null
  ): Promise<void> {
    if (!userId || !titleId) return;
    const db = this.getDbInstance();
    const docRef = doc(db, 'users', userId, 'userTitles', titleId);

    if (status === null) {
      await deleteDoc(docRef);
    } else {
      await setDoc(docRef, {
        status,
        userId,
        updatedAt: serverTimestamp(),
      });
    }
  }
}

export const firestoreUserDataAdapter = new FirestoreUserDataAdapter();
