import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TriggerScannerModal } from '../components/TriggerScannerModal';

describe('TriggerScannerModal', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
  });

  it('opens the public protected GitHub Actions workflow without a browser credential', () => {
    vi.stubEnv('VITE_GITHUB_OWNER', 'testowner');
    vi.stubEnv('VITE_GITHUB_REPO', 'testrepo');

    render(<TriggerScannerModal />);

    const link = screen.getByTestId('trigger-scanner-button');
    expect(link).toHaveAttribute(
      'href',
      'https://github.com/testowner/testrepo/actions/workflows/scanner.yml'
    );
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.queryByText(/token/i)).not.toBeInTheDocument();
  });

  it('renders an unconfigured state when the public repository is unknown', () => {
    render(<TriggerScannerModal />);

    expect(screen.getByTestId('trigger-scanner-unconfigured')).toBeInTheDocument();
    expect(screen.queryByTestId('trigger-scanner-button')).not.toBeInTheDocument();
  });
});
