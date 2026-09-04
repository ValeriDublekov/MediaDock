import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { CatalogView } from '../components/CatalogView';
import { CatalogRepository, Title } from '../domain/catalog';

describe('Catalog Filter & Search UI Component Interactions', () => {
  let mockRepository: CatalogRepository;

  const date1 = new Date('2026-08-05T12:00:00Z');
  const date2 = new Date('2026-08-04T12:00:00Z');

  const item1: Title = {
    id: 'tt001',
    title: 'Interstellar',
    normalizedTitle: 'interstellar',
    year: 2014,
    mediaType: 'movie',
    firstSeenAt: date1,
    lastSeenAt: date1,
    updatedAt: date1,
    imdbRating: 8.7,
    imdbVotes: 1800000,
    countries: ['USA'],
    genres: ['Sci-Fi', 'Drama'],
    director: 'Christopher Nolan',
  };

  const item2: Title = {
    id: 'tt002',
    title: 'Sherlock',
    normalizedTitle: 'sherlock',
    year: 2010,
    mediaType: 'series',
    firstSeenAt: date2,
    lastSeenAt: date2,
    updatedAt: date2,
    imdbRating: 9.1,
    imdbVotes: 900000,
    countries: ['UK'],
    genres: ['Crime', 'Mystery'],
    director: 'Steven Moffat',
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockRepository = {
      getCatalogPage: vi.fn(),
      getTitleById: vi.fn(),
      getOccurrences: vi.fn(),
    };
  });

  it('renders filter bar and search scope notice', async () => {
    vi.mocked(mockRepository.getCatalogPage).mockResolvedValueOnce({
      items: [item1, item2],
      nextCursor: null,
      hasMore: false,
    });

    render(<CatalogView repository={mockRepository} pageSize={10} />);

    await waitFor(() => {
      expect(screen.getByText('Interstellar')).toBeInTheDocument();
      expect(screen.getByText('Sherlock')).toBeInTheDocument();
    });

    expect(screen.getByTestId('catalog-filter-bar')).toBeInTheDocument();
    expect(screen.getByTestId('search-scope-notice')).toBeInTheDocument();
    expect(
      screen.getByText('Search and filters apply to 2 of 2 loaded items')
    ).toBeInTheDocument();
  });

  it('filters loaded items dynamically via search input', async () => {
    const user = userEvent.setup();

    vi.mocked(mockRepository.getCatalogPage).mockResolvedValueOnce({
      items: [item1, item2],
      nextCursor: null,
      hasMore: false,
    });

    render(<CatalogView repository={mockRepository} pageSize={10} />);

    await waitFor(() => {
      expect(screen.getByText('Interstellar')).toBeInTheDocument();
    });

    const searchInput = screen.getByTestId('catalog-search-input');
    await user.type(searchInput, 'Sherlock');

    await waitFor(() => {
      expect(screen.queryByText('Interstellar')).not.toBeInTheDocument();
      expect(screen.getByText('Sherlock')).toBeInTheDocument();
    });

    // Clear search
    const clearBtn = screen.getByTestId('catalog-search-clear');
    await user.click(clearBtn);

    await waitFor(() => {
      expect(screen.getByText('Interstellar')).toBeInTheDocument();
      expect(screen.getByText('Sherlock')).toBeInTheDocument();
    });
  });

  it('renders empty-filtered state when no loaded items match criteria', async () => {
    const user = userEvent.setup();

    vi.mocked(mockRepository.getCatalogPage).mockResolvedValueOnce({
      items: [item1, item2],
      nextCursor: { lastSeenAt: date2, id: item2.id },
      hasMore: true,
    });

    render(<CatalogView repository={mockRepository} pageSize={10} />);

    await waitFor(() => {
      expect(screen.getByText('Interstellar')).toBeInTheDocument();
    });

    const searchInput = screen.getByTestId('catalog-search-input');
    await user.type(searchInput, 'NonExistentTitleX');

    await waitFor(() => {
      expect(screen.getByTestId('catalog-empty-filtered')).toBeInTheDocument();
      expect(screen.getByText('Няма намерени заглавия')).toBeInTheDocument();
    });

    expect(screen.getByTestId('clear-filters-button')).toBeInTheDocument();
    expect(screen.queryByTestId('catalog-load-more-from-empty-button')).not.toBeInTheDocument();

    // Reset filters restores list
    const clearBtn = screen.getByTestId('clear-filters-button');
    await user.click(clearBtn);

    await waitFor(() => {
      expect(screen.getByText('Interstellar')).toBeInTheDocument();
      expect(screen.getByText('Sherlock')).toBeInTheDocument();
    });
  });

  it('sorts loaded items using sort selector', async () => {
    const user = userEvent.setup();

    vi.mocked(mockRepository.getCatalogPage).mockResolvedValueOnce({
      items: [item1, item2],
      nextCursor: null,
      hasMore: false,
    });

    render(<CatalogView repository={mockRepository} pageSize={10} />);

    await waitFor(() => {
      expect(screen.getByText('Interstellar')).toBeInTheDocument();
    });

    const sortSelect = screen.getByTestId('catalog-sort-select');
    await user.selectOptions(sortSelect, 'titleAsc');

    await waitFor(() => {
      const cards = screen.getAllByTestId('title-card');
      expect(cards[0]).toHaveTextContent('Interstellar');
      expect(cards[1]).toHaveTextContent('Sherlock');
    });
  });

  it('expands filter panel and allows toggling media type and rating sliders', async () => {
    const user = userEvent.setup();

    vi.mocked(mockRepository.getCatalogPage).mockResolvedValueOnce({
      items: [item1, item2],
      nextCursor: null,
      hasMore: false,
    });

    render(<CatalogView repository={mockRepository} pageSize={10} />);

    await waitFor(() => {
      expect(screen.getByText('Interstellar')).toBeInTheDocument();
    });

    const expandBtn = screen.getByTestId('toggle-filters-expand');
    await user.click(expandBtn);

    await waitFor(() => {
      expect(screen.getByTestId('filter-panel-content')).toBeInTheDocument();
      expect(screen.getByTestId('filter-mediatype-movie')).toBeInTheDocument();
      expect(screen.getByTestId('filter-mediatype-series')).toBeInTheDocument();
    });

    // Toggle off movies
    await user.click(screen.getByTestId('filter-mediatype-movie'));

    await waitFor(() => {
      expect(screen.queryByText('Interstellar')).not.toBeInTheDocument();
      expect(screen.getByText('Sherlock')).toBeInTheDocument();
    });
  });
});
