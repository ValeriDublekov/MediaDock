import React from 'react';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AuthProvider, useAuth } from '../application/AuthContext';
import { AuthGate } from '../components/AuthGate';
import { AuthAdapter, User } from '../domain/auth';

describe('Authentication Flow', () => {
  let mockAdapter: AuthAdapter;
  let authStateCallback: (user: User | null) => void;

  beforeEach(() => {
    mockAdapter = {
      onAuthStateChanged: vi.fn((cb) => {
        authStateCallback = cb;
        return vi.fn();
      }),
      signInWithGoogle: vi.fn().mockResolvedValue(undefined),
      signOut: vi.fn().mockResolvedValue(undefined),
    };
  });

  const TestApp = ({ children }: { children?: React.ReactNode }) => (
    <AuthProvider adapter={mockAdapter}>
      <AuthGate>
        {children || <div data-testid="catalog">Catalog Content</div>}
      </AuthGate>
    </AuthProvider>
  );

  it('shows loading state initially, then sign in button when no user', async () => {
    render(<TestApp />);
    
    expect(screen.getByTestId('auth-loading')).toBeInTheDocument();
    
    act(() => {
      authStateCallback(null);
    });
    
    await waitFor(() => {
      expect(screen.getByTestId('signin-button')).toBeInTheDocument();
    });
    
    expect(screen.queryByTestId('auth-loading')).not.toBeInTheDocument();
    expect(screen.queryByTestId('catalog')).not.toBeInTheDocument();
  });

  it('calls signInWithGoogle on button click', async () => {
    render(<TestApp />);
    act(() => {
      authStateCallback(null);
    });
    
    const user = userEvent.setup();
    const signInButton = await screen.findByTestId('signin-button');
    
    await user.click(signInButton);
    expect(mockAdapter.signInWithGoogle).toHaveBeenCalledTimes(1);
  });

  it('renders catalog when user is signed in', async () => {
    render(<TestApp />);
    act(() => {
      authStateCallback({ uid: '123', email: 'test@example.com', displayName: 'Test User' });
    });
    
    await waitFor(() => {
      expect(screen.getByTestId('catalog')).toBeInTheDocument();
    });
    expect(screen.getByTestId('user-email')).toHaveTextContent('test@example.com');
  });

  it('calls signOut on header button click', async () => {
    render(<TestApp />);
    act(() => {
      authStateCallback({ uid: '123', email: 'test@example.com', displayName: 'Test User' });
    });
    
    const user = userEvent.setup();
    const signOutButton = await screen.findByTestId('header-signout-button');
    
    await user.click(signOutButton);
    expect(mockAdapter.signOut).toHaveBeenCalledTimes(1);
  });

  it('shows access denied state when setAccessDenied is called', async () => {
    const AccessToggler = () => {
      const { setAccessDenied } = useAuth();
      return (
        <button onClick={() => setAccessDenied(true)} data-testid="deny-access">
          Deny Access
        </button>
      );
    };

    render(
      <TestApp>
        <AccessToggler />
      </TestApp>
    );
    
    act(() => {
      authStateCallback({ uid: '123', email: 'test@example.com', displayName: 'Test User' });
    });
    
    const user = userEvent.setup();
    const denyButton = await screen.findByTestId('deny-access');
    await user.click(denyButton);
    
    expect(await screen.findByTestId('access-denied-message')).toBeInTheDocument();
    expect(screen.getByTestId('signout-button')).toBeInTheDocument();
  });
});
