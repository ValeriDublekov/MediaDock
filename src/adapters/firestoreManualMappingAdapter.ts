import {
  collection,
  getDocs,
  doc,
  setDoc,
  deleteDoc,
  Timestamp,
  Firestore,
  DocumentData,
  QueryDocumentSnapshot,
} from 'firebase/firestore';
import { getAuth, getDb } from './firebaseApp';
import { ManualMapping, ManualMappingRepository } from '../domain/manualMapping';

function toDate(val: unknown): Date {
  if (!val) return new Date();
  if (typeof (val as { toDate?: () => Date }).toDate === 'function') {
    return (val as { toDate: () => Date }).toDate();
  }
  if (val instanceof Date) return val;
  if (typeof val === 'number' || typeof val === 'string') return new Date(val);
  return new Date();
}

function mapDocToManualMapping(docSnap: QueryDocumentSnapshot<DocumentData>): ManualMapping {
  const data = docSnap.data();
  return {
    id: docSnap.id,
    rawTitle: data.rawTitle ?? '',
    imdbId: data.imdbId ?? '',
    createdAt: toDate(data.createdAt),
    parsedTitle: data.parsedTitle ?? null,
    parsedYear: typeof data.parsedYear === 'number' ? data.parsedYear : null,
    createdBy: data.createdBy ?? null,
  };
}

export class FirestoreManualMappingAdapter implements ManualMappingRepository {
  constructor(private getDbInstance: () => Firestore = getDb) {}

  async getManualMappings(): Promise<ManualMapping[]> {
    const db = this.getDbInstance();
    const mappingsRef = collection(db, 'manualMappings');

    try {
      const snapshot = await getDocs(mappingsRef);
      const mappings = snapshot.docs.map(mapDocToManualMapping);
      mappings.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
      return mappings;
    } catch (err: unknown) {
      const errStr = String(err);
      if (errStr.includes('permission-denied') || errStr.includes('Missing or insufficient permissions')) {
        throw new Error(
          'Missing or insufficient permissions за колекцията "manualMappings". Уверете се, че сте логнати с позволен акаунт.'
        );
      }
      throw err;
    }
  }

  async saveManualMapping(mapping: Omit<ManualMapping, 'createdAt'>): Promise<void> {
    const db = this.getDbInstance();
    const userId = getAuth().currentUser?.uid;
    if (!userId) {
      throw new Error('Authentication required to save a manual mapping.');
    }
    const imdbId = mapping.imdbId.trim();
    if (!/^tt[0-9]{7,10}$/.test(imdbId)) {
      throw new Error('A valid IMDb ID is required.');
    }
    const docRef = doc(db, 'manualMappings', mapping.id);

    const payload: Record<string, unknown> = {
      rawTitle: mapping.rawTitle,
      imdbId,
      createdAt: Timestamp.now(),
      parsedTitle: mapping.parsedTitle,
      parsedYear: mapping.parsedYear,
      createdBy: userId,
    };

    await setDoc(docRef, payload, { merge: true });
  }

  async deleteManualMapping(mappingId: string): Promise<void> {
    const db = this.getDbInstance();
    const docRef = doc(db, 'manualMappings', mappingId);
    await deleteDoc(docRef);
  }
}

export const firestoreManualMappingAdapter = new FirestoreManualMappingAdapter();
