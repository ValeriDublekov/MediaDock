import { initializeApp, FirebaseApp } from 'firebase/app';
import { getAuth as getFirebaseAuth, Auth } from 'firebase/auth';
import { getFirestore as getFirebaseFirestore, Firestore } from 'firebase/firestore';

let appInstance: FirebaseApp | null = null;
let authInstance: Auth | null = null;
let dbInstance: Firestore | null = null;

export function getAuth(): Auth {
  if (!authInstance) {
    const apiKey = import.meta.env.VITE_FIREBASE_API_KEY;
    if (!apiKey) {
      throw new Error('Firebase configuration missing. Set VITE_FIREBASE_API_KEY in your environment.');
    }
    
    const firebaseConfig = {
      apiKey,
      authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
      projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
      storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
      messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
      appId: import.meta.env.VITE_FIREBASE_APP_ID,
    };

    appInstance = initializeApp(firebaseConfig);
    authInstance = getFirebaseAuth(appInstance);
  }
  return authInstance;
}

export function getDb(): Firestore {
  if (!dbInstance) {
    if (!appInstance) {
      getAuth();
    }
    dbInstance = getFirebaseFirestore(appInstance!);
  }
  return dbInstance;
}

