import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TriggerScannerModal } from '../components/TriggerScannerModal';

describe('TriggerScannerModal', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders trigger button and settings icon button', () => {
    render(<TriggerScannerModal />);

    const button = screen.getByTestId('trigger-scanner-button');
    expect(button).toBeInTheDocument();
    expect(button).toHaveTextContent('Действия');

    const settingsBtn = screen.getByTestId('scanner-settings-button');
    expect(settingsBtn).toBeInTheDocument();

    // Modal should not be open initially
    expect(screen.queryByTestId('scanner-modal')).not.toBeInTheDocument();
    expect(screen.queryByTestId('scanner-actions-modal')).not.toBeInTheDocument();
  });

  it('opens settings modal when settings gear button is clicked', () => {
    render(<TriggerScannerModal />);

    fireEvent.click(screen.getByTestId('scanner-settings-button'));

    expect(screen.getByTestId('scanner-modal')).toBeInTheDocument();
    expect(screen.getByText('Настройки за Сканиране')).toBeInTheDocument();
  });

  it('performs dispatch directly when action is clicked and credentials exist in localStorage', async () => {
    localStorage.setItem('movies_feed_gh_owner', 'testowner');
    localStorage.setItem('movies_feed_gh_repo', 'testrepo');
    localStorage.setItem('movies_feed_gh_pat', 'ghp_savedtoken');
    localStorage.setItem('movies_feed_gh_force_days', '2');

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      status: 204,
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<TriggerScannerModal />);

    // Click trigger button directly to open actions menu
    fireEvent.click(screen.getByTestId('trigger-scanner-button'));
    
    // Click the RSS scan action
    fireEvent.click(screen.getByTestId('action-btn-rss'));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        'https://api.github.com/repos/testowner/testrepo/actions/workflows/scanner.yml/dispatches',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer ghp_savedtoken',
          }),
          body: JSON.stringify({
            ref: 'main',
            inputs: {
              dry_run: false,
              force_days: '2',
              mode: 'rss',
            },
          }),
        })
      );
    });

    // Check success status toast message
    await waitFor(() => {
      expect(screen.getByTestId('scanner-status-message')).toHaveTextContent(
        'Действието (rss) е стартирано успешно в GitHub Actions!'
      );
    });
  });

  it('allows selecting force_days in settings modal', () => {
    render(<TriggerScannerModal />);

    fireEvent.click(screen.getByTestId('scanner-settings-button'));

    const select = screen.getByTestId('select-force-days') as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    expect(select.value).toBe('0');

    fireEvent.change(select, { target: { value: '2' } });
    expect(select.value).toBe('2');
  });

  it('opens settings modal if credentials are missing on action click', async () => {
    vi.stubEnv('VITE_GITHUB_PAT', '');
    vi.stubEnv('VITE_GITHUB_OWNER', '');
    render(<TriggerScannerModal />);

    fireEvent.click(screen.getByTestId('trigger-scanner-button'));
    fireEvent.click(screen.getByTestId('action-btn-rss'));

    // Should automatically prompt settings modal because token/owner are missing
    expect(screen.getByTestId('scanner-modal')).toBeInTheDocument();
    
    // Check error status toast inside modal
    expect(screen.getByTestId('scanner-status-message-modal')).toHaveTextContent(
      'Моля, въведете GitHub Owner, Repo и Token преди да стартирате действие.'
    );
  });
});
