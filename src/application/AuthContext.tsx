import React, { createContext, useContext, useEffect, useState } from 'react';
import { AuthAdapter, User } from '../domain/auth';

export interface AuthState {
  user: User | null;
  loading: boolean;
  error: string | null;
  accessDenied: boolean;
}

export interface AuthContextValue extends AuthState {
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  setAccessDenied: (denied: boolean) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({
  adapter,
  children,
}: {
  adapter: AuthAdapter;
  children: React.ReactNode;
}) {
  const [state, setState] = useState<AuthState>({
    user: null,
    loading: true,
    error: null,
    accessDenied: false,
  });

  useEffect(() => {
    const unsubscribe = adapter.onAuthStateChanged((user) => {
      setState((s) => ({ ...s, user, loading: false, error: null, accessDenied: false }));
    });
    return unsubscribe;
  }, [adapter]);

  const value: AuthContextValue = {
    ...state,
    signInWithGoogle: async () => {
      try {
        setState((s) => ({ ...s, error: null, accessDenied: false }));
        await adapter.signInWithGoogle();
      } catch (err) {
        setState((s) => ({
          ...s,
          error: err instanceof Error ? err.message : 'Login failed',
        }));
      }
    },
    signOut: async () => {
      try {
        await adapter.signOut();
      } catch (err) {
        setState((s) => ({
          ...s,
          error: err instanceof Error ? err.message : 'Sign out failed',
        }));
      }
    },
    setAccessDenied: (denied: boolean) => {
      setState((s) => ({ ...s, accessDenied: denied }));
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
