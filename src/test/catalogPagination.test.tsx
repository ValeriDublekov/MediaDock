import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { CatalogView } from '../components/CatalogView';
import { CatalogRepository, Title } from '../domain/catalog';

describe('Catalog Query and Pagination', () => {
  let mockRepository: CatalogRepository;

  const date1 = new Date('2026-08-05T12:00:00Z');
  const date2 = new Date('2026-08-04T12:00:00Z');
  const date3 = new Date('2026-08-03T12:00:00Z');

  const item1: Title = {
    id: 'tt001',
    title: 'Movie One',
    normalizedTitle: 'movie one',
    year: 2024,
    mediaType: 'movie',
    firstSeenAt: date1,
    lastSeenAt: date1,
    updatedAt: date1,
    imdbRating: 8.1,
  };

  const item2: Title = {
    id: 'tt002',
    title: 'Series Two',
    normalizedTitle: 'series two',
    year: 2023,
    mediaType: 'series',
    firstSeenAt: date2,
    lastSeenAt: date2,
    updatedAt: date2,
    imdbRating: 7.5,
  };

  const item3: Title = {
    id: 'tt003',
    title: 'Movie Three',
    normalizedTitle: 'movie three',
    year: 2025,
    mediaType: 'movie',
    firstSeenAt: date3,
    lastSeenAt: date3,
    updatedAt: date3,
    imdbRating: 9.0,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockRepository = {
      getCatalogPage: vi.fn(),
      getLatestRssSnapshotPage: vi.fn(),
      getTitleById: vi.fn(),
      getOccurrences: vi.fn(),
    };
  });

  it('loads every movie snapshot page automatically and preserves RSS order', async () => {
    const nextCursor = { snapshotId: 'snapshot-1', rssPosition: 1, titleId: item1.id };
    vi.mocked(mockRepository.getLatestRssSnapshotPage!)
      .mockResolvedValueOnce({
        items: [item1],
        nextCursor,
        hasMore: true,
        snapshotId: 'snapshot-1',
      })
      .mockResolvedValueOnce({
        items: [item3],
        nextCursor: null,
        hasMore: false,
        snapshotId: 'snapshot-1',
      });

    render(<CatalogView repository={mockRepository} pageSize={1} />);

    await waitFor(() => expect(screen.getByText('Movie Three')).toBeInTheDocument());

    expect(mockRepository.getLatestRssSnapshotPage).toHaveBeenNthCalledWith(1, {
      pageSize: 1,
      sourceType: 'movie',
      cursor: null,
    });
    expect(mockRepository.getLatestRssSnapshotPage).toHaveBeenNthCalledWith(2, {
      pageSize: 1,
      sourceType: 'movie',
      cursor: nextCursor,
    });
    expect(screen.getAllByTestId('title-card').map((card) => card.textContent)).toEqual([
      expect.stringContaining('Movie One'),
      expect.stringContaining('Movie Three'),
    ]);
    expect(screen.queryByTestId('catalog-load-more-button')).not.toBeInTheDocument();
    expect(mockRepository.getCatalogPage).not.toHaveBeenCalled();
  });

  it('renders only Movies and Series tabs and switches RSS category', async () => {
    vi.mocked(mockRepository.getLatestRssSnapshotPage!).mockImplementation(async ({ sourceType }) => ({
      items: sourceType === 'movie' ? [item1] : [item2],
      nextCursor: null,
      hasMore: false,
      snapshotId: 'snapshot-1',
    }));
    const user = userEvent.setup();

    render(<CatalogView repository={mockRepository} pageSize={2} />);

    await waitFor(() => expect(screen.getByText('Movie One')).toBeInTheDocument());
    expect(screen.getByTestId('view-mode-movies')).toBeInTheDocument();
    expect(screen.getByTestId('view-mode-series')).toBeInTheDocument();
    expect(screen.queryByTestId('view-mode-latest')).not.toBeInTheDocument();
    expect(screen.queryByTestId('view-mode-catalog')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('view-mode-series'));

    await waitFor(() => expect(screen.getByText('Series Two')).toBeInTheDocument());
    expect(screen.queryByText('Movie One')).not.toBeInTheDocument();
    expect(mockRepository.getLatestRssSnapshotPage).toHaveBeenLastCalledWith({
      pageSize: 2,
      sourceType: 'series',
      cursor: null,
    });
  });

  it('shows an explicit state when no successful RSS snapshot exists', async () => {
    vi.mocked(mockRepository.getLatestRssSnapshotPage!).mockResolvedValueOnce({
      items: [],
      nextCursor: null,
      hasMore: false,
      snapshotId: null,
    });

    render(<CatalogView repository={mockRepository} pageSize={2} />);

    await waitFor(() => {
      expect(screen.getByTestId('catalog-no-latest-snapshot')).toBeInTheDocument();
    });
    expect(screen.getByText('Няма успешно RSS сканиране')).toBeInTheDocument();
  });

  it('suppresses duplicate titles across automatic snapshot pages', async () => {
    vi.mocked(mockRepository.getLatestRssSnapshotPage!)
      .mockResolvedValueOnce({
        items: [item1],
        nextCursor: { snapshotId: 'snapshot-1', rssPosition: 0, titleId: item1.id },
        hasMore: true,
        snapshotId: 'snapshot-1',
      })
      .mockResolvedValueOnce({
        items: [item1, item3],
        nextCursor: null,
        hasMore: false,
        snapshotId: 'snapshot-1',
      });

    render(<CatalogView repository={mockRepository} pageSize={1} />);

    await waitFor(() => expect(screen.getByText('Movie Three')).toBeInTheDocument());
    expect(screen.getAllByTestId('title-card')).toHaveLength(2);
  });

  it('restarts automatic snapshot loading cleanly after a page error', async () => {
    const user = userEvent.setup();
    const nextCursor = { snapshotId: 'snapshot-1', rssPosition: 0, titleId: item1.id };
    vi.mocked(mockRepository.getLatestRssSnapshotPage!)
      .mockResolvedValueOnce({
        items: [item1],
        nextCursor,
        hasMore: true,
        snapshotId: 'snapshot-1',
      })
      .mockRejectedValueOnce(new Error('Page 2 fetch failed'))
      .mockResolvedValueOnce({
        items: [item1],
        nextCursor,
        hasMore: true,
        snapshotId: 'snapshot-1',
      })
      .mockResolvedValueOnce({
        items: [item3],
        nextCursor: null,
        hasMore: false,
        snapshotId: 'snapshot-1',
      });

    render(<CatalogView repository={mockRepository} pageSize={1} />);

    await waitFor(() => {
      expect(screen.getByTestId('catalog-error')).toBeInTheDocument();
      expect(screen.getByText('Page 2 fetch failed')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('catalog-retry-button'));

    await waitFor(() => expect(screen.getByText('Movie Three')).toBeInTheDocument());

    expect(screen.queryByTestId('catalog-error')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('title-card')).toHaveLength(2);
    expect(mockRepository.getLatestRssSnapshotPage).toHaveBeenCalledTimes(4);
  });

  it('keeps both tabs available when the selected category is empty', async () => {
    vi.mocked(mockRepository.getLatestRssSnapshotPage!).mockResolvedValueOnce({
      items: [],
      nextCursor: null,
      hasMore: false,
      snapshotId: 'snapshot-1',
    });

    render(<CatalogView repository={mockRepository} pageSize={2} />);

    await waitFor(() => expect(screen.getByText('Няма намерени заглавия')).toBeInTheDocument());
    expect(screen.getByTestId('view-mode-movies')).toBeInTheDocument();
    expect(screen.getByTestId('view-mode-series')).toBeInTheDocument();
  });
});
