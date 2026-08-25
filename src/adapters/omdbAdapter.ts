import { getAuth } from './firebaseApp';
import { Title } from '../domain/catalog';
import { firestoreManualMappingAdapter } from './firestoreManualMappingAdapter';

export const saveTitleManualMapping = async (title: Title, imdbId: string): Promise<void> => {
  const normalizedImdbId = imdbId.trim();
  if (!/^tt[0-9]{7,10}$/.test(normalizedImdbId)) {
    throw new Error('A valid IMDb ID is required.');
  }

  const userId = getAuth().currentUser?.uid;
  if (!userId) {
    throw new Error('Authentication required to save a manual mapping.');
  }

  await firestoreManualMappingAdapter.saveManualMapping({
    id: title.id,
    rawTitle: title.title,
    imdbId: normalizedImdbId,
    parsedTitle: title.title,
    parsedYear: title.year,
    createdBy: userId,
  });
};
