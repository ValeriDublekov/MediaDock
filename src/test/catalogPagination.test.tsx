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
      getTitleById: vi.fn(),
      getOccurrences: vi.fn(),
    };
  });

  it('loads first page and renders titles with load more button', async () => {
    vi.mocked(mockRepository.getCatalogPage).mockResolvedValueOnce({
      items: [item1, item2],
      nextCursor: { lastSeenAt: date2, id: item2.id },
      hasMore: true,
    });

    render(<CatalogView repository={mockRepository} pageSize={2} />);

    expect(screen.getByTestId('catalog-loading')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Movie One')).toBeInTheDocument();
      expect(screen.getByText('Series Two')).toBeInTheDocument();
    });

    expect(mockRepository.getCatalogPage).toHaveBeenCalledWith({
      pageSize: 2,
      cursor: null,
    });

    expect(screen.getByTestId('catalog-load-more-button')).toBeInTheDocument();
  });

  it('uses the latest RSS snapshot as the initial source and preserves its order', async () => {
    const latestRepository: CatalogRepository = {
      ...mockRepository,
      getLatestRssSnapshotPage: vi.fn().mockResolvedValueOnce({
        items: [item2, item1],
        nextCursor: null,
        hasMore: false,
        snapshotId: 'snapshot-1',
      }),
    };

    render(<CatalogView repository={latestRepository} pageSize={2} />);

    await waitFor(() => {
      expect(screen.getByText('Series Two')).toBeInTheDocument();
      expect(screen.getByText('Movie One')).toBeInTheDocument();
    });

    expect(latestRepository.getLatestRssSnapshotPage).toHaveBeenCalledWith({
      pageSize: 2,
      cursor: null,
    });
    expect(latestRepository.getCatalogPage).not.toHaveBeenCalled();
    const titleCards = screen.getAllByTestId('title-card');
    expect(titleCards[0]).toHaveTextContent('Series Two');
    expect(titleCards[1]).toHaveTextContent('Movie One');
  });

  it('shows an explicit state when no successful RSS snapshot exists', async () => {
    const latestRepository: CatalogRepository = {
      ...mockRepository,
      getLatestRssSnapshotPage: vi.fn().mockResolvedValueOnce({
        items: [],
        nextCursor: null,
        hasMore: false,
        snapshotId: null,
      }),
    };

    render(<CatalogView repository={latestRepository} pageSize={2} />);

    await waitFor(() => {
      expect(screen.getByTestId('catalog-no-latest-snapshot')).toBeInTheDocument();
    });
    expect(screen.getByText('Няма успешно RSS сканиране')).toBeInTheDocument();
  });

  it('switches from Latest to the historical Catalog source', async () => {
    const user = userEvent.setup();
    const latestRepository: CatalogRepository = {
      ...mockRepository,
      getLatestRssSnapshotPage: vi.fn().mockResolvedValueOnce({
        items: [item1],
        nextCursor: null,
        hasMore: false,
        snapshotId: 'snapshot-1',
      }),
    };
    vi.mocked(latestRepository.getCatalogPage).mockResolvedValueOnce({
      items: [item3],
      nextCursor: null,
      hasMore: false,
    });

    render(<CatalogView repository={latestRepository} pageSize={2} />);

    await waitFor(() => {
      expect(screen.getByText('Movie One')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('view-mode-catalog'));

    await waitFor(() => {
      expect(screen.getByText('Movie Three')).toBeInTheDocument();
    });
    expect(latestRepository.getCatalogPage).toHaveBeenCalledWith({
      pageSize: 2,
      cursor: null,
    });
  });

  it('passes next cursor when load more is clicked', async () => {
    const user = userEvent.setup();

    vi.mocked(mockRepository.getCatalogPage)
      .mockResolvedValueOnce({
        items: [item1, item2],
        nextCursor: { lastSeenAt: date2, id: item2.id },
        hasMore: true,
      })
      .mockResolvedValueOnce({
        items: [item3],
        nextCursor: null,
        hasMore: false,
      });

    render(<CatalogView repository={mockRepository} pageSize={2} />);

    await waitFor(() => {
      expect(screen.getByText('Movie One')).toBeInTheDocument();
    });

    const loadMoreBtn = screen.getByTestId('catalog-load-more-button');
    await user.click(loadMoreBtn);

    await waitFor(() => {
      expect(screen.getByText('Movie Three')).toBeInTheDocument();
    });

    expect(mockRepository.getCatalogPage).toHaveBeenNthCalledWith(2, {
      pageSize: 2,
      cursor: { lastSeenAt: date2, id: item2.id },
    });

    expect(screen.getAllByTestId('title-card')).toHaveLength(3);
  });

  it('suppresses duplicate items returned in subsequent pages', async () => {
    const user = userEvent.setup();

    // Page 1 returns item1, item2
    // Page 2 returns item2 (duplicate!), item3
    vi.mocked(mockRepository.getCatalogPage)
      .mockResolvedValueOnce({
        items: [item1, item2],
        nextCursor: { lastSeenAt: date2, id: item2.id },
        hasMore: true,
      })
      .mockResolvedValueOnce({
        items: [item2, item3],
        nextCursor: null,
        hasMore: false,
      });

    render(<CatalogView repository={mockRepository} pageSize={2} />);

    await waitFor(() => {
      expect(screen.getByText('Movie One')).toBeInTheDocument();
    });

    const loadMoreBtn = screen.getByTestId('catalog-load-more-button');
    await user.click(loadMoreBtn);

    await waitFor(() => {
      expect(screen.getByText('Movie Three')).toBeInTheDocument();
    });

    // Should only have 3 title cards rendered, item2 should not be duplicated
    const titleCards = screen.getAllByTestId('title-card');
    expect(titleCards).toHaveLength(3);
  });

  it('handles retry on initial page load error', async () => {
    const user = userEvent.setup();

    vi.mocked(mockRepository.getCatalogPage)
      .mockRejectedValueOnce(new Error('Firestore network timeout'))
      .mockResolvedValueOnce({
        items: [item1],
        nextCursor: null,
        hasMore: false,
      });

    render(<CatalogView repository={mockRepository} pageSize={10} />);

    await waitFor(() => {
      expect(screen.getByTestId('catalog-error')).toBeInTheDocument();
      expect(screen.getByText('Firestore network timeout')).toBeInTheDocument();
    });

    const retryBtn = screen.getByTestId('catalog-retry-button');
    await user.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByText('Movie One')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('catalog-error')).not.toBeInTheDocument();
    expect(mockRepository.getCatalogPage).toHaveBeenCalledTimes(2);
  });

  it('handles retry when pagination load fails', async () => {
    const user = userEvent.setup();

    vi.mocked(mockRepository.getCatalogPage)
      .mockResolvedValueOnce({
        items: [item1],
        nextCursor: { lastSeenAt: date1, id: item1.id },
        hasMore: true,
      })
      .mockRejectedValueOnce(new Error('Page 2 fetch failed'))
      .mockResolvedValueOnce({
        items: [item2],
        nextCursor: null,
        hasMore: false,
      });

    render(<CatalogView repository={mockRepository} pageSize={1} />);

    await waitFor(() => {
      expect(screen.getByText('Movie One')).toBeInTheDocument();
    });

    const loadMoreBtn = screen.getByTestId('catalog-load-more-button');
    await user.click(loadMoreBtn);

    await waitFor(() => {
      expect(screen.getByTestId('catalog-error')).toBeInTheDocument();
      expect(screen.getByText('Failed to load next page: Page 2 fetch failed')).toBeInTheDocument();
    });

    const retryBtn = screen.getByTestId('catalog-retry-button');
    await user.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByText('Series Two')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('catalog-error')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('title-card')).toHaveLength(2);
  });

  it('renders end-of-results state on final page and hides load more button', async () => {
    vi.mocked(mockRepository.getCatalogPage).mockResolvedValueOnce({
      items: [item1],
      nextCursor: null,
      hasMore: false,
    });

    render(<CatalogView repository={mockRepository} pageSize={10} />);

    await waitFor(() => {
      expect(screen.getByText('Movie One')).toBeInTheDocument();
    });

    expect(screen.getByTestId('catalog-end-of-results')).toBeInTheDocument();
    expect(screen.getByText('End of catalog')).toBeInTheDocument();
    expect(screen.queryByTestId('catalog-load-more-button')).not.toBeInTheDocument();
  });

  it('renders empty state when initial page has no titles', async () => {
    vi.mocked(mockRepository.getCatalogPage).mockResolvedValueOnce({
      items: [],
      nextCursor: null,
      hasMore: false,
    });

    render(<CatalogView repository={mockRepository} pageSize={10} />);

    await waitFor(() => {
      expect(screen.getByTestId('catalog-empty')).toBeInTheDocument();
      expect(screen.getByText('Catalog is empty')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('catalog-list')).not.toBeInTheDocument();
  });
});
