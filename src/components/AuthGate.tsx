import React from 'react';
import { useAuth } from '../application/AuthContext';
import { LogOut } from 'lucide-react';

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading, error, accessDenied, signInWithGoogle, signOut } = useAuth();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-neutral-50" data-testid="auth-loading">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-neutral-900"></div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-neutral-50 px-4">
        <div className="w-full max-w-sm p-8 bg-white rounded-2xl shadow-sm border border-neutral-100 text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-neutral-900 mb-2">MoviesFeed</h1>
          <p className="text-sm text-neutral-500 mb-8">Sign in to access the catalog</p>
          
          <button
            onClick={signInWithGoogle}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium text-white bg-neutral-900 hover:bg-neutral-800 rounded-lg transition-colors"
            data-testid="signin-button"
          >
            Sign in with Google
          </button>
          
          {error && (
            <p className="mt-4 text-sm text-red-600" data-testid="auth-error">
              {error}
            </p>
          )}
        </div>
      </div>
    );
  }

  if (accessDenied) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-neutral-50 px-4">
        <div className="w-full max-w-sm p-8 bg-white rounded-2xl shadow-sm border border-neutral-100 text-center">
          <div className="w-12 h-12 bg-red-50 text-red-600 rounded-full flex items-center justify-center mx-auto mb-4">
            <LogOut className="w-6 h-6" />
          </div>
          <h2 className="text-xl font-semibold tracking-tight text-neutral-900 mb-2">Access Denied</h2>
          <p className="text-sm text-neutral-500 mb-8" data-testid="access-denied-message">
            Your account ({user.email}) is not authorized to view this catalog.
          </p>
          
          <button
            onClick={signOut}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-neutral-700 bg-neutral-100 hover:bg-neutral-200 rounded-lg transition-colors"
            data-testid="signout-button"
          >
            Sign Out
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-neutral-50">
      <header className="bg-white border-b border-neutral-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <h1 className="text-lg font-semibold text-neutral-900">MoviesFeed</h1>
          <div className="flex items-center gap-4">
            <span className="text-sm text-neutral-600" data-testid="user-email">{user.email}</span>
            <button
              onClick={signOut}
              className="p-2 text-neutral-500 hover:text-neutral-900 hover:bg-neutral-100 rounded-md transition-colors"
              title="Sign Out"
              data-testid="header-signout-button"
            >
              <LogOut className="w-5 h-5" />
            </button>
          </div>
        </div>
      </header>
      <main>
        {children}
      </main>
    </div>
  );
}
