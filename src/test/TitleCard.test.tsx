import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { TitleCard } from '../components/TitleCard';
import { PosterImage } from '../components/PosterImage';
import { CatalogSkeleton } from '../components/CatalogSkeleton';
import { Title, Occurrence, CatalogRepository } from '../domain/catalog';

describe('Catalog Presentation Components', () => {
  const sampleMovie: Title = {
    id: 'tt1234567',
    title: 'Inception',
    normalizedTitle: 'inception',
    year: 2010,
    mediaType: 'movie',
    firstSeenAt: new Date('2026-08-01T12:00:00Z'),
    lastSeenAt: new Date('2026-08-05T12:00:00Z'),
    updatedAt: new Date('2026-08-05T12:00:00Z'),
    imdbId: 'tt1234567',
    imdbRating: 8.8,
    imdbVotes: 2400000,
    metascore: 74,
    genres: ['Action', 'Sci-Fi', 'Thriller'],
    countries: ['USA', 'UK'],
    director: 'Christopher Nolan',
    plot: 'A thief who steals corporate secrets through dream-sharing technology.',
    posterUrl: 'https://example.com/inception.jpg',
    runtime: '148 min',
    awards: 'Won 4 Oscars',
  };

  const sampleSeries: Title = {
    id: 'tt0944947',
    title: 'Game of Thrones',
    normalizedTitle: 'game of thrones',
    year: 2011,
    mediaType: 'series',
    firstSeenAt: new Date('2026-08-01T12:00:00Z'),
    lastSeenAt: new Date('2026-08-05T12:00:00Z'),
    updatedAt: new Date('2026-08-05T12:00:00Z'),
    imdbId: 'tt0944947',
    imdbRating: 9.2,
    posterUrl: null,
  };

  const sampleOccurrences: Occurrence[] = [
    {
      id: 'occ-1',
      sourceFeedId: 'feed-1',
      sourceFeedName: 'RuTracker Movies',
      feedEntryId: 'entry-1',
      torrentUrl: 'https://example.com/torrent1.torrent',
      rawTitle: 'Inception (2010) 1080p BDRip',
      quality: '1080p',
      ripType: 'BDRip',
      firstSeenAt: new Date('2026-08-01T12:00:00Z'),
      lastSeenAt: new Date('2026-08-05T12:00:00Z'),
    },
  ];

  it('renders title card with complete metadata, ratings, and media type badge', () => {
    render(<TitleCard title={sampleMovie} />);

    expect(screen.getByTestId('title-card')).toBeInTheDocument();
    expect(screen.getByTestId('title-heading')).toHaveTextContent('Inception');
    expect(screen.getByTestId('title-year')).toHaveTextContent('2010');
    expect(screen.getByTestId('media-type-badge')).toHaveTextContent('Movie');
    expect(screen.getByTestId('rating-badge')).toHaveTextContent('8.8');
    expect(screen.getByTestId('metascore-badge')).toHaveTextContent('Metascore: 74');
    expect(screen.getByText('Dir: Christopher Nolan')).toBeInTheDocument();
    expect(screen.getByText('Action')).toBeInTheDocument();
    expect(screen.getByText('Sci-Fi')).toBeInTheDocument();
    expect(screen.getByText('2.4M votes')).toBeInTheDocument();
  });

  it('renders safe IMDb link with target="_blank" and rel="noopener noreferrer"', () => {
    render(<TitleCard title={sampleMovie} />);

    const imdbLink = screen.getByTestId('imdb-link');
    expect(imdbLink).toBeInTheDocument();
    expect(imdbLink).toHaveAttribute('href', 'https://www.imdb.com/title/tt1234567/');
    expect(imdbLink).toHaveAttribute('target', '_blank');
    expect(imdbLink).toHaveAttribute('rel', 'noopener noreferrer');
    expect(imdbLink).toHaveAttribute('aria-label', 'View Inception on IMDb (opens in new tab)');
  });

  it('renders image fallback when posterUrl is null or fails to load', () => {
    const { rerender } = render(<TitleCard title={sampleSeries} />);

    // When posterUrl is null
    expect(screen.getByTestId('poster-fallback')).toBeInTheDocument();
    expect(screen.getByText('Game of Thrones')).toBeInTheDocument();

    // When posterUrl exists but fails to load
    rerender(<PosterImage posterUrl="https://invalid-domain.com/broken.jpg" title="Broken Image Title" />);
    const img = screen.getByAltText('Broken Image Title poster');
    fireEvent.error(img);

    expect(screen.getByTestId('poster-fallback')).toBeInTheDocument();
  });

  it('fetches and displays occurrences with quality and ripType indicators safely', async () => {
    const user = userEvent.setup();
    const mockRepo: CatalogRepository = {
      getCatalogPage: vi.fn(),
      getTitleById: vi.fn(),
      getOccurrences: vi.fn().mockResolvedValue(sampleOccurrences),
    };

    render(<TitleCard title={sampleMovie} repository={mockRepo} />);

    const toggleBtn = screen.getByTestId('toggle-torrents-button');
    await user.click(toggleBtn);

    await waitFor(() => {
      expect(screen.getByTestId('occurrences-list')).toBeInTheDocument();
      expect(screen.getByTestId('quality-badge')).toHaveTextContent('1080p');
      expect(screen.getByTestId('riptype-badge')).toHaveTextContent('BDRip');
    });

    const torrentLink = screen.getByTestId('torrent-link');
    expect(torrentLink).toHaveAttribute('href', 'https://example.com/torrent1.torrent');
    expect(torrentLink).toHaveAttribute('target', '_blank');
    expect(torrentLink).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders CatalogSkeleton loading placeholders', () => {
    render(<CatalogSkeleton count={4} />);

    expect(screen.getByTestId('catalog-loading')).toBeInTheDocument();
    expect(screen.getAllByTestId('catalog-skeleton')).toHaveLength(4);
  });
});
