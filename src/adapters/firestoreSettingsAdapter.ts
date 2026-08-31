/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { doc, getDoc, setDoc, Firestore } from 'firebase/firestore';
import { getAuth, getDb } from './firebaseApp';
import { GlobalSettings, SettingsRepository, DEFAULT_SETTINGS, isValidSettings } from '../domain/settings';

export class FirestoreSettingsAdapter implements SettingsRepository {
  constructor(private getDbInstance: () => Firestore = getDb) {}

  async getSettings(): Promise<GlobalSettings> {
    try {
      const db = this.getDbInstance();
      const docRef = doc(db, 'titles', 'settings_config');
      const docSnap = await getDoc(docRef);

      if (!docSnap.exists()) {
        return DEFAULT_SETTINGS;
      }

      const data = docSnap.data();
      return {
        rssFeeds: data.rssFeeds ?? DEFAULT_SETTINGS.rssFeeds,
        excludedGenres: Array.isArray(data.excludedGenres) ? data.excludedGenres : DEFAULT_SETTINGS.excludedGenres,
        excludedCountries: Array.isArray(data.excludedCountries) ? data.excludedCountries : DEFAULT_SETTINGS.excludedCountries,
        minMovieRating: typeof data.minMovieRating === 'number' ? data.minMovieRating : DEFAULT_SETTINGS.minMovieRating,
        minSeriesRating: typeof data.minSeriesRating === 'number' ? data.minSeriesRating : DEFAULT_SETTINGS.minSeriesRating,
        minImdbVotes: typeof data.minImdbVotes === 'number' ? data.minImdbVotes : DEFAULT_SETTINGS.minImdbVotes,
      };
    } catch (err) {
      console.warn('Failed to load settings from Firestore, using defaults:', err);
      return DEFAULT_SETTINGS;
    }
  }

  async saveSettings(settings: GlobalSettings): Promise<void> {
    if (!isValidSettings(settings)) {
      throw new Error('Scanner settings are invalid. Review the settings and try again.');
    }

    const db = this.getDbInstance();
    const userId = getAuth().currentUser?.uid;
    if (!userId) {
      throw new Error('Authentication required to update scanner settings.');
    }
    const docRef = doc(db, 'titles', 'settings_config');
    await setDoc(docRef, {
      rssFeeds: settings.rssFeeds,
      excludedGenres: settings.excludedGenres,
      excludedCountries: settings.excludedCountries,
      minMovieRating: settings.minMovieRating,
      minSeriesRating: settings.minSeriesRating,
      minImdbVotes: settings.minImdbVotes,
      updatedBy: userId,
    });
  }
}

export const firestoreSettingsAdapter = new FirestoreSettingsAdapter();
