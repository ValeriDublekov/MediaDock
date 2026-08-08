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
    expect(button).toHaveTextContent('Стартирай сканиране');

    const settingsBtn = screen.getByTestId('scanner-settings-button');
    expect(settingsBtn).toBeInTheDocument();

    // Modal should not be open initially
    expect(screen.queryByTestId('scanner-modal')).not.toBeInTheDocument();
  });

  it('opens settings modal when settings gear button is clicked', () => {
    render(<TriggerScannerModal />);

    fireEvent.click(screen.getByTestId('scanner-settings-button'));

    expect(screen.getByTestId('scanner-modal')).toBeInTheDocument();
    expect(screen.getByText('Настройки за RSS Сканиране')).toBeInTheDocument();
  });

  it('performs 1-click dispatch directly when credentials exist in localStorage', async () => {
    localStorage.setItem('movies_feed_gh_owner', 'testowner');
    localStorage.setItem('movies_feed_gh_repo', 'testrepo');
    localStorage.setItem('movies_feed_gh_pat', 'ghp_savedtoken');

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      status: 204,
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<TriggerScannerModal />);

    // Click trigger button directly
    fireEvent.click(screen.getByTestId('trigger-scanner-button'));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        'https://api.github.com/repos/testowner/testrepo/actions/workflows/scanner.yml/dispatches',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer ghp_savedtoken',
          }),
        })
      );
    });

    // Check success status toast message
    await waitFor(() => {
      expect(screen.getByTestId('scanner-status-message')).toHaveTextContent(
        'Сканирането е стартирано успешно в GitHub Actions!'
      );
    });
  });

  it('opens modal if credentials are missing on 1-click trigger', async () => {
    render(<TriggerScannerModal />);

    fireEvent.click(screen.getByTestId('trigger-scanner-button'));

    // Should automatically prompt modal because token/owner are missing
    expect(screen.getByTestId('scanner-modal')).toBeInTheDocument();
  });
});
