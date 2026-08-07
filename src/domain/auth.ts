export interface User {
  uid: string;
  email: string | null;
  displayName: string | null;
}

export interface AuthAdapter {
  onAuthStateChanged(callback: (user: User | null) => void): () => void;
  signInWithGoogle(): Promise<void>;
  signOut(): Promise<void>;
}
