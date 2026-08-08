import {
  collection,
  getDocs,
  query,
  orderBy,
  limit,
  Timestamp,
  Firestore,
  DocumentData,
  QueryDocumentSnapshot,
} from 'firebase/firestore';
import { getDb } from './firebaseApp';
import { ParseLog, ParseLogRepository } from '../domain/parseLog';

function toDate(val: unknown): Date {
  if (!val) return new Date(0);
  if (typeof (val as { toDate?: () => Date }).toDate === 'function') {
    return (val as { toDate: () => Date }).toDate();
  }
  if (val instanceof Date) return val;
  if (typeof val === 'number' || typeof val === 'string') return new Date(val);
  return new Date(0);
}

function mapDocToParseLog(docSnap: QueryDocumentSnapshot<DocumentData>): ParseLog {
  const data = docSnap.data();
  return {
    id: docSnap.id,
    rawTitle: data.rawTitle ?? '',
    feedName: data.feedName ?? '',
    parsedSuccessfully: Boolean(data.parsedSuccessfully),
    parsedTitle: data.parsedTitle ?? null,
    parsedYear: typeof data.parsedYear === 'number' ? data.parsedYear : null,
    omdbStatus: data.omdbStatus ?? 'not_parsed',
    ignored: Boolean(data.ignored),
    ignoreReason: data.ignoreReason ?? null,
    processedAt: toDate(data.processedAt),
  };
}

export class FirestoreParseLogAdapter implements ParseLogRepository {
  constructor(private getDbInstance: () => Firestore = getDb) {}

  async getRecentParseLogs(limitCount: number = 100): Promise<ParseLog[]> {
    const db = this.getDbInstance();
    const logsRef = collection(db, 'parseLogs');

    // Query ordered by processedAt desc with limit
    const q = query(
      logsRef,
      orderBy('processedAt', 'desc'),
      limit(limitCount)
    );

    const snapshot = await getDocs(q);
    const logs = snapshot.docs.map(mapDocToParseLog);

    // Filter to retain only entries from the last 7 days (1 week retention rule)
    const oneWeekAgoMs = Date.now() - 7 * 24 * 60 * 60 * 1000;
    return logs.filter((log) => log.processedAt.getTime() >= oneWeekAgoMs);
  }
}

export const firestoreParseLogAdapter = new FirestoreParseLogAdapter();
