import {
  collection,
  doc,
  getDoc,
  getDocs,
  query,
  orderBy,
  limit,
  startAfter,
  documentId,
  Timestamp,
  Firestore,
  DocumentData,
  QueryDocumentSnapshot,
  QueryConstraint,
  where,
} from 'firebase/firestore';
import { getDb } from './firebaseApp';
import {
  CatalogRepository,
  CatalogPageOptions,
  CatalogPage,
  CatalogCursor,
  LatestRssSnapshotCursor,
  LatestRssSnapshotPage,
  RssSourceType,
  Title,
  Occurrence,
} from '../domain/catalog';
import {
  mapOccurrenceDocument,
  mapRssSnapshotItemDocument,
  mapRssSnapshotStateDocument,
  mapTitleDocument,
  toDate,
} from './firestoreCatalogMappers';

export class FirestoreCatalogAdapter implements CatalogRepository {
  constructor(private getDbInstance: () => Firestore = getDb) {}

  async getLatestRssSnapshotPage(options: {
    pageSize: number;
    sourceType: RssSourceType;
    cursor?: LatestRssSnapshotCursor | null;
  }): Promise<LatestRssSnapshotPage> {
    const db = this.getDbInstance();
    const cursor = options.cursor ?? null;
    const snapshotId = cursor?.snapshotId ?? await this.getCurrentSnapshotId(db);

    if (!snapshotId) {
      return {
        items: [],
        nextCursor: null,
        hasMore: false,
        snapshotId: null,
      };
    }

    const itemsRef = collection(db, 'rssSnapshots', snapshotId, 'items');
    const constraints: QueryConstraint[] = [
      where('sourceType', '==', options.sourceType),
      orderBy('rssPosition', 'asc'),
    ];
    if (cursor) {
      constraints.push(startAfter(cursor.rssPosition));
    }
    constraints.push(limit(options.pageSize + 1));

    const snapshot = await getDocs(query(itemsRef, ...constraints));
    const hasMore = snapshot.docs.length > options.pageSize;
    const pageDocs = hasMore ? snapshot.docs.slice(0, options.pageSize) : snapshot.docs;
    const snapshotItems = pageDocs.map((itemDoc) =>
      mapRssSnapshotItemDocument(itemDoc.data() as DocumentData, itemDoc.id)
    );
    const titleIds = snapshotItems.map((item) => item.titleId);
    const hydratedTitles = titleIds.length > 0 ? await this.getTitlesByIds(titleIds) : [];
    const titlesById = new Map(hydratedTitles.map((title) => [title.id, title]));
    const items = titleIds
      .map((titleId) => titlesById.get(titleId))
      .filter((title): title is Title => title !== undefined);

    let nextCursor: LatestRssSnapshotCursor | null = null;
    const lastItem = snapshotItems[snapshotItems.length - 1];
    if (lastItem && hasMore) {
      nextCursor = {
        snapshotId,
        rssPosition: lastItem.rssPosition,
        titleId: lastItem.titleId,
      };
    }

    return {
      items,
      nextCursor,
      hasMore,
      snapshotId,
    };
  }

  private async getCurrentSnapshotId(db: Firestore): Promise<string | null> {
    const stateSnapshot = await getDoc(doc(db, 'rssSnapshotState', 'current'));
    if (!stateSnapshot.exists()) return null;
    try {
      return mapRssSnapshotStateDocument(
        stateSnapshot.data() as DocumentData
      ).snapshotId;
    } catch {
      return null;
    }
  }

  async getCatalogPage(options: CatalogPageOptions): Promise<CatalogPage> {
    const db = this.getDbInstance();
    const titlesRef = collection(db, 'titles');
    const sourceConstraint = options.sourceType
      ? [where('sourceType', '==', options.sourceType)]
      : [];

    const q = options.cursor
      ? query(
          titlesRef,
          ...sourceConstraint,
          orderBy('lastSeenAt', 'desc'),
          orderBy(documentId(), 'desc'),
          startAfter(
            Timestamp.fromDate(options.cursor.lastSeenAt),
            options.cursor.id
          ),
          limit(options.pageSize)
        )
      : query(
          titlesRef,
          ...sourceConstraint,
          orderBy('lastSeenAt', 'desc'),
          orderBy(documentId(), 'desc'),
          limit(options.pageSize)
        );
    const snapshot = await getDocs(q);
        const items = snapshot.docs.map((docSnap) =>
          mapTitleDocument(docSnap.id, docSnap.data() as DocumentData)
        );
    const hasMore = snapshot.docs.length === options.pageSize;
    const lastDoc = snapshot.docs[snapshot.docs.length - 1];
    let nextCursor: CatalogCursor | null = null;
    if (lastDoc && hasMore) {
      const lastData = lastDoc.data() as DocumentData;
      nextCursor = {
        lastSeenAt: toDate(lastData['lastSeenAt']),
        id: lastDoc.id,
      };
    }

    return {
      items,
      nextCursor,
      hasMore,
    };
  }

  async getTitleById(id: string): Promise<Title | null> {
    const db = this.getDbInstance();
    const docRef = doc(db, 'titles', id);
    const docSnap = await getDoc(docRef);

    if (!docSnap.exists()) {
      return null;
    }

    return mapTitleDocument(docSnap.id, docSnap.data() as DocumentData);
  }

  async getTitlesByIds(ids: string[]): Promise<Title[]> {
    if (!ids || ids.length === 0) return [];
    const db = this.getDbInstance();
    const titlesRef = collection(db, 'titles');
    const uniqueIds = Array.from(new Set(ids));
    const results: Title[] = [];

    // Chunk into batches of 30 for documentId() in [...]
    const chunkSize = 30;
    for (let i = 0; i < uniqueIds.length; i += chunkSize) {
      const chunk = uniqueIds.slice(i, i + chunkSize);
      const q = query(titlesRef, where(documentId(), 'in', chunk));
      const snapshot = await getDocs(q);
      snapshot.docs.forEach((docSnap) => {
        results.push(mapTitleDocument(docSnap.id, docSnap.data() as DocumentData));
      });
    }

    return results;
  }

  async getOccurrences(titleId: string): Promise<Occurrence[]> {
    const db = this.getDbInstance();
    const occurrencesRef = collection(db, 'titles', titleId, 'occurrences');
    const q = query(occurrencesRef, orderBy('firstSeenAt', 'desc'));
    const snapshot = await getDocs(q);

    return snapshot.docs.map((docSnap) =>
      mapOccurrenceDocument(docSnap.id, docSnap.data() as DocumentData)
    );
  }
}

export const firestoreCatalogAdapter = new FirestoreCatalogAdapter();
