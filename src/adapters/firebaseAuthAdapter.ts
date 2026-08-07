import { GoogleAuthProvider, onAuthStateChanged, signInWithPopup, signOut } from 'firebase/auth';
import { getAuth } from './firebaseApp';
import { AuthAdapter } from '../domain/auth';

export const firebaseAuthAdapter: AuthAdapter = {
  onAuthStateChanged: (callback) => {
    try {
      const auth = getAuth();
      return onAuthStateChanged(auth, (firebaseUser) => {
        if (firebaseUser) {
          callback({
            uid: firebaseUser.uid,
            email: firebaseUser.email,
            displayName: firebaseUser.displayName,
          });
        } else {
          callback(null);
        }
      });
    } catch (error) {
      console.warn('Firebase Auth initialization failed:', error);
      callback(null);
      return () => {};
    }
  },
  signInWithGoogle: async () => {
    const auth = getAuth();
    const provider = new GoogleAuthProvider();
    await signInWithPopup(auth, provider);
  },
  signOut: async () => {
    const auth = getAuth();
    await signOut(auth);
  },
};
