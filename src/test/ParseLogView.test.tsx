import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ParseLogView } from '../components/ParseLogView';
import { ParseLog, ParseLogRepository } from '../domain/parseLog';
import { ManualMapping, ManualMappingRepository } from '../domain/manualMapping';

const mockLogs: ParseLog[] = [
  {
    id: 'log-1',
    rawTitle: 'The Matrix 1999 1080p BluRay',
    feedName: 'movies_hd',
    parsedSuccessfully: true,
    parsedTitle: 'The Matrix',
    parsedYear: 1999,
    omdbStatus: 'found',
    ignored: false,
    ignoreReason: null,
    processedAt: new Date(),
  },
  {
    id: 'log-2',
    rawTitle: 'Some Obscure Film 2022 HDTV',
    feedName: 'movies_hd',
    parsedSuccessfully: true,
    parsedTitle: 'Some Obscure Film',
    parsedYear: 2022,
    omdbStatus: 'not_found',
    ignored: true,
    ignoreReason: 'omdb_not_found',
    processedAt: new Date(Date.now() - 3600 * 1000),
  },
  {
    id: 'log-3',
    rawTitle: 'Excluded Movie 2021 BDRip',
    feedName: 'movies_sd',
    parsedSuccessfully: true,
    parsedTitle: 'Excluded Movie',
    parsedYear: 2021,
    omdbStatus: 'found',
    ignored: true,
    ignoreReason: 'excluded_country_or_genre',
    processedAt: new Date(Date.now() - 7200 * 1000),
  },
  {
    id: 'log-4',
    rawTitle: 'Garbage Unparseable Title ###',
    feedName: 'movies_sd',
    parsedSuccessfully: false,
    parsedTitle: null,
    parsedYear: null,
    omdbStatus: 'not_parsed',
    ignored: true,
    ignoreReason: 'no_title',
    processedAt: new Date(Date.now() - 10800 * 1000),
  },
];

class MockParseLogRepo implements ParseLogRepository {
  async getRecentParseLogs(): Promise<ParseLog[]> {
    return mockLogs;
  }
}

class MockManualMappingRepo implements ManualMappingRepository {
  mappings: ManualMapping[] = [];

  async getManualMappings(): Promise<ManualMapping[]> {
    return this.mappings;
  }

  async saveManualMapping(mapping: Omit<ManualMapping, 'createdAt'>): Promise<void> {
    this.mappings.push({
      ...mapping,
      createdAt: new Date(),
    });
  }

  async deleteManualMapping(mappingId: string): Promise<void> {
    this.mappings = this.mappings.filter((m) => m.id !== mappingId);
  }
}

describe('ParseLogView', () => {
  it('renders metrics and parse log rows correctly', async () => {
    const repo = new MockParseLogRepo();
    render(<ParseLogView repository={repo} />);

    await waitFor(() => {
      expect(screen.getByTestId('metric-total')).toHaveTextContent('4');
      expect(screen.getByTestId('metric-parsed')).toHaveTextContent('3');
      expect(screen.getByTestId('metric-omdb')).toHaveTextContent('2');
      expect(screen.getByTestId('metric-ignored')).toHaveTextContent('3');
    });

    expect(screen.getByText('The Matrix 1999 1080p BluRay')).toBeInTheDocument();
    expect(screen.getAllByText('Some Obscure Film 2022 HDTV').length).toBeGreaterThan(0);
  });

  it('filters logs by search input', async () => {
    const repo = new MockParseLogRepo();
    render(<ParseLogView repository={repo} />);

    await waitFor(() => {
      expect(screen.getByTestId('metric-total')).toHaveTextContent('4');
    });

    const searchInput = screen.getByTestId('parse-log-search-input');
    fireEvent.change(searchInput, { target: { value: 'Matrix' } });

    expect(screen.getByText('The Matrix 1999 1080p BluRay')).toBeInTheDocument();
    expect(screen.queryByText('Some Obscure Film 2022 HDTV')).not.toBeInTheDocument();
  });

  it('filters logs by active filter tab', async () => {
    const repo = new MockParseLogRepo();
    render(<ParseLogView repository={repo} />);

    await waitFor(() => {
      expect(screen.getByTestId('metric-total')).toHaveTextContent('4');
    });

    // Click 'Ignored' filter tab
    const ignoredTab = screen.getByTestId('filter-tab-ignored');
    fireEvent.click(ignoredTab);

    expect(screen.queryByText('The Matrix 1999 1080p BluRay')).not.toBeInTheDocument();
    expect(screen.getByText('Some Obscure Film 2022 HDTV')).toBeInTheDocument();
    expect(screen.getByText('Excluded Movie 2021 BDRip')).toBeInTheDocument();
  });

  it('allows user to enter and save an IMDb ID for unfound titles', async () => {
    const parseRepo = new MockParseLogRepo();
    const mappingRepo = new MockManualMappingRepo();

    render(<ParseLogView repository={parseRepo} manualMappingRepository={mappingRepo} />);

    await waitFor(() => {
      expect(screen.getByTestId('metric-unfound')).toHaveTextContent('1');
      expect(screen.getByTestId('unfound-titles-section')).toBeInTheDocument();
    });

    const imdbInput = screen.getByTestId('imdb-input-log-2');
    const saveButton = screen.getByTestId('save-mapping-button-log-2');

    fireEvent.change(imdbInput, { target: { value: 'tt0133093' } });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mappingRepo.mappings.length).toBe(1);
      expect(mappingRepo.mappings[0].imdbId).toBe('tt0133093');
    });
  });
});
