import React, { useState, useEffect } from 'react';
import { Title, Occurrence, CatalogRepository } from '../domain/catalog';
import { firestoreCatalogAdapter } from '../adapters/firestoreCatalogAdapter';
import { updateTitleWithOmdb } from '../adapters/omdbAdapter';
import { PosterImage } from './PosterImage';
import { TitleDetailModal } from './TitleDetailModal';
import { Star, ExternalLink, Download, Film, Layers, Award, Clock, Globe, RefreshCw, Edit2, Check, X, Loader2, Info } from 'lucide-react';

interface TitleCardProps {
  title: Title;
  repository?: CatalogRepository;
  occurrences?: Occurrence[];
}

export const TitleCard: React.FC<TitleCardProps> = ({
  title,
  repository = firestoreCatalogAdapter,
  occurrences: initialOccurrences,
}) => {
  const [currentTitle, setCurrentTitle] = useState<Title>(title);
  const [occurrences, setOccurrences] = useState<Occurrence[] | undefined>(initialOccurrences);
  const [isLoadingOccurrences, setIsLoadingOccurrences] = useState(false);
  const [showOccurrences, setShowOccurrences] = useState(false);
  const [isEditingId, setIsEditingId] = useState(false);
  const [editImdbId, setEditImdbId] = useState(title.imdbId || '');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);

  useEffect(() => {
    setCurrentTitle(title);
    setEditImdbId(title.imdbId || '');
  }, [title]);

  useEffect(() => {
    let isMounted = true;
    if (!initialOccurrences && repository && showOccurrences && !occurrences) {
      setIsLoadingOccurrences(true);
      repository
        .getOccurrences(currentTitle.id)
        .then((fetched) => {
          if (isMounted) {
            setOccurrences(fetched);
            setIsLoadingOccurrences(false);
          }
        })
        .catch(() => {
          if (isMounted) {
            setOccurrences([]);
            setIsLoadingOccurrences(false);
          }
        });
    }
    return () => {
      isMounted = false;
    };
  }, [initialOccurrences, repository, showOccurrences, currentTitle.id, occurrences]);

  const handleRefreshOmdb = async (targetImdbId?: string) => {
    const apiKey = localStorage.getItem('movies_feed_omdb_api_key') || import.meta.env.VITE_OMDB_API_KEY || import.meta.env.OMDB_API_KEY;
    if (!apiKey) {
      setRefreshError('Missing OMDb API Key. Set it in Scanner Settings.');
      return;
    }
    const idToUse = targetImdbId || currentTitle.imdbId;
    if (!idToUse) {
      setRefreshError('No IMDb ID available to refresh.');
      return;
    }

    setIsRefreshing(true);
    setRefreshError(null);
    try {
      const updatedTitleData = await updateTitleWithOmdb(currentTitle, idToUse, apiKey);
      if (updatedTitleData) {
        setCurrentTitle(updatedTitleData);
      }
      setIsEditingId(false);
    } catch (err: any) {
      setRefreshError(err.message || 'Failed to update from OMDb');
    } finally {
      setIsRefreshing(false);
    }
  };

  // Format media type label and badge style
  const formatMediaType = (type: string) => {
    const lower = type.toLowerCase();
    if (lower === 'movie') return { label: 'Movie', className: 'bg-neutral-800 text-neutral-200 border-neutral-700' };
    if (lower === 'series' || lower === 'tv series')
      return { label: 'TV Series', className: 'bg-emerald-950 text-emerald-300 border-emerald-800' };
    if (lower === 'documentary')
      return { label: 'Documentary', className: 'bg-sky-950 text-sky-300 border-sky-800' };
    if (lower === 'short' || lower === 'short movie')
      return { label: 'Short Movie', className: 'bg-purple-950 text-purple-300 border-purple-800' };
    return { label: type, className: 'bg-neutral-800 text-neutral-300 border-neutral-700' };
  };

  const mediaTypeInfo = formatMediaType(currentTitle.mediaType);

  // Format vote counts cleanly (e.g. 12,345 -> 12.3k)
  const formatVotes = (votes: number | null | undefined) => {
    if (!votes) return null;
    if (votes >= 1000000) return `${(votes / 1000000).toFixed(1)}M votes`;
    if (votes >= 1000) return `${(votes / 1000).toFixed(1)}k votes`;
    return `${votes} votes`;
  };

  return (
    <>
      <article
        data-testid="title-card"
        className="bg-neutral-900 border border-neutral-800 rounded-xl overflow-hidden shadow-sm hover:border-neutral-700 transition-all flex flex-col justify-between group focus-within:ring-2 focus-within:ring-amber-500/50"
      >
        <div
          onClick={() => setIsDetailModalOpen(true)}
          className="cursor-pointer"
          title="Кликнете за пълна информация за филма"
          data-testid="title-card-click-area"
        >
          {/* Poster Grid & Rating Overlay */}
          <div className="relative aspect-[2/3] w-full overflow-hidden bg-neutral-950">
            <PosterImage
              posterUrl={currentTitle.posterUrl}
              title={currentTitle.title}
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            />

            {/* Rating Badge Overlay */}
            {currentTitle.imdbRating !== null && currentTitle.imdbRating !== undefined && (
              <div
                data-testid="rating-badge"
                className="absolute top-3 right-3 bg-neutral-950/90 backdrop-blur-md border border-amber-500/40 text-amber-400 text-xs font-bold px-2.5 py-1 rounded-md flex items-center gap-1 shadow-md z-10"
                aria-label={`IMDb Rating: ${currentTitle.imdbRating} out of 10`}
              >
                <Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" aria-hidden="true" />
                <span>{currentTitle.imdbRating.toFixed(1)}</span>
              </div>
            )}

            {/* Media Type Badge Overlay */}
            <div className="absolute top-3 left-3 z-10">
              <span
                data-testid="media-type-badge"
                className={`inline-block text-[11px] font-bold px-2.5 py-0.5 rounded-md border backdrop-blur-md shadow-xs ${mediaTypeInfo.className}`}
              >
                {mediaTypeInfo.label}
              </span>
            </div>

            {/* Hover overlay hint */}
            <div className="absolute inset-0 bg-neutral-950/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center p-2">
              <span className="px-3 py-1.5 rounded-lg bg-neutral-950/80 backdrop-blur-md border border-amber-500/40 text-amber-400 text-xs font-semibold flex items-center gap-1.5 shadow-xl">
                <Info className="w-3.5 h-3.5" />
                <span>Пълна информация</span>
              </span>
            </div>
          </div>

          {/* Card Body & Metadata */}
          <div className="p-4 space-y-3">
            {/* Header Title & Year */}
            <div>
              <div className="flex items-start justify-between gap-2">
                <h3
                  data-testid="title-heading"
                  className="font-bold text-neutral-100 text-base leading-snug line-clamp-1 group-hover:text-amber-400 transition-colors"
                  title={currentTitle.title}
                >
                  {currentTitle.title}
                </h3>
                {currentTitle.year && (
                  <span
                    data-testid="title-year"
                    className="text-xs font-semibold px-2 py-0.5 rounded bg-neutral-800 text-neutral-300 border border-neutral-700 shrink-0"
                  >
                    {currentTitle.year}
                  </span>
                )}
              </div>

              {/* Director / Countries */}
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-neutral-400 mt-1">
                {currentTitle.director && <span className="text-neutral-300">Dir: {currentTitle.director}</span>}
                {currentTitle.countries && currentTitle.countries.length > 0 && (
                  <span className="flex items-center gap-1 text-neutral-400">
                    <Globe className="w-3 h-3 text-neutral-500" aria-hidden="true" />
                    {currentTitle.countries.join(', ')}
                  </span>
                )}
              </div>
            </div>

            {/* Ratings & Metadata Pills */}
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {currentTitle.metascore !== null && currentTitle.metascore !== undefined && (
                <span
                  data-testid="metascore-badge"
                  className={`font-semibold px-1.5 py-0.5 rounded text-[10px] border ${
                    currentTitle.metascore >= 60
                      ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                      : currentTitle.metascore >= 40
                      ? 'bg-amber-950 text-amber-300 border-amber-800'
                      : 'bg-red-950 text-red-300 border-red-800'
                  }`}
                  title="Metascore"
                >
                  Metascore: {currentTitle.metascore}
                </span>
              )}

              {currentTitle.imdbVotes ? (
                <span className="text-neutral-400 text-[11px]">
                  {formatVotes(currentTitle.imdbVotes)}
                </span>
              ) : null}

              {currentTitle.runtime && (
                <span className="flex items-center gap-1 text-neutral-400 text-[11px]">
                  <Clock className="w-3 h-3 text-neutral-500" aria-hidden="true" />
                  {currentTitle.runtime}
                </span>
              )}
            </div>

            {/* Genres */}
            {currentTitle.genres && currentTitle.genres.length > 0 && (
              <div className="flex flex-wrap gap-1" data-testid="genres-list">
                {currentTitle.genres.map((genre) => (
                  <span
                    key={genre}
                    className="text-[11px] px-2 py-0.5 rounded bg-neutral-800/80 text-neutral-300 border border-neutral-700/60"
                  >
                    {genre}
                  </span>
                ))}
              </div>
            )}

            {/* Plot Summary */}
            {currentTitle.plot && (
              <p className="text-xs text-neutral-400 line-clamp-2 leading-relaxed" title={currentTitle.plot}>
                {currentTitle.plot}
              </p>
            )}

            {/* Awards */}
            {currentTitle.awards && (
              <div className="flex items-center gap-1.5 text-[11px] text-amber-300/80 bg-amber-950/30 border border-amber-900/40 p-2 rounded-md">
                <Award className="w-3.5 h-3.5 text-amber-400 shrink-0" aria-hidden="true" />
                <span className="truncate">{currentTitle.awards}</span>
              </div>
            )}
          </div>
        </div>

        {/* Footer & Safe External Links */}
        <div className="p-4 pt-2 border-t border-neutral-800/80 space-y-2">
          <div className="flex items-center justify-between gap-2">
            {/* IMDb Safe Link & Edit Controls */}
            <div className="flex-1 flex items-center gap-2">
              {currentTitle.imdbId ? (
                <a
                  href={`https://www.imdb.com/title/${currentTitle.imdbId}/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  aria-label={`View ${currentTitle.title} on IMDb (opens in new tab)`}
                  data-testid="imdb-link"
                  className="flex-1 min-h-[44px] px-3 py-2 text-xs font-semibold rounded-lg bg-amber-500 hover:bg-amber-400 text-neutral-950 flex items-center justify-center gap-1.5 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-400 cursor-pointer"
                >
                  <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>IMDb</span>
                </a>
              ) : (
                <span className="flex-1 text-[11px] text-neutral-500 italic py-2">No IMDb Link</span>
              )}

              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsEditingId(!isEditingId);
                }}
                className="w-11 h-11 flex items-center justify-center rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-400 hover:text-neutral-200 border border-neutral-700 transition-colors"
                title="Edit IMDb ID"
              >
                <Edit2 className="w-4 h-4" />
              </button>
              
              {currentTitle.imdbId && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRefreshOmdb();
                  }}
                  disabled={isRefreshing}
                  className="w-11 h-11 flex items-center justify-center rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-400 hover:text-neutral-200 border border-neutral-700 transition-colors disabled:opacity-50"
                  title="Refresh from OMDb"
                >
                  {isRefreshing && !isEditingId ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <RefreshCw className="w-4 h-4" />
                  )}
                </button>
              )}
            </div>

            {/* Torrent / Occurrences Trigger Button */}
            {repository && !initialOccurrences && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowOccurrences(!showOccurrences);
                }}
                aria-expanded={showOccurrences}
                aria-label={`Toggle torrent links for ${currentTitle.title}`}
                data-testid="toggle-torrents-button"
                className="min-h-[44px] px-3 py-2 text-xs font-medium rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-200 border border-neutral-700 flex items-center justify-center gap-1.5 transition-colors focus:outline-none focus:ring-2 focus:ring-neutral-500 cursor-pointer"
              >
                <Download className="w-3.5 h-3.5 text-neutral-400" aria-hidden="true" />
                <span>{showOccurrences ? 'Hide Torrents' : 'Torrents'}</span>
              </button>
            )}
          </div>

          {/* Inline Edit Form */}
          {isEditingId && (
            <div className="flex items-center gap-2 mt-2 pt-2 border-t border-neutral-800" onClick={(e) => e.stopPropagation()}>
              <input
                type="text"
                value={editImdbId}
                onChange={(e) => setEditImdbId(e.target.value)}
                placeholder="tt1234567"
                className="flex-1 px-3 py-2 bg-neutral-950 border border-neutral-700 rounded-lg text-sm text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500 font-mono"
              />
              <button
                onClick={() => handleRefreshOmdb(editImdbId)}
                disabled={!editImdbId || isRefreshing}
                className="px-3 py-2 bg-amber-500 hover:bg-amber-400 text-neutral-950 rounded-lg text-sm font-semibold flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50"
              >
                {isRefreshing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                Save
              </button>
              <button
                onClick={() => setIsEditingId(false)}
                className="px-3 py-2 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 rounded-lg text-sm font-medium transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* Refresh Error */}
          {refreshError && (
            <div className="text-xs text-red-400 mt-1 bg-red-950/40 p-2 rounded border border-red-900/50">
              {refreshError}
            </div>
          )}

          {/* Occurrences / Torrent Downloads List */}
          {showOccurrences && (
            <div className="pt-2 border-t border-neutral-800 space-y-2" data-testid="occurrences-list" onClick={(e) => e.stopPropagation()}>
              {isLoadingOccurrences ? (
                <div className="text-xs text-neutral-400 py-2 text-center animate-pulse">
                  Loading torrent links...
                </div>
              ) : occurrences && occurrences.length > 0 ? (
                <div className="space-y-1.5">
                  {occurrences.map((occ) => (
                    <a
                      key={occ.id}
                      href={occ.torrentUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`Download torrent ${occ.rawTitle || title.title}`}
                      data-testid="torrent-link"
                      className="flex items-center justify-between p-2 rounded bg-neutral-950 hover:bg-neutral-800 border border-neutral-800 hover:border-neutral-700 text-xs text-neutral-200 transition-colors group/torrent"
                    >
                      <div className="flex items-center gap-2 overflow-hidden">
                        <Download className="w-3.5 h-3.5 text-blue-400 shrink-0 group-hover/torrent:text-blue-300" aria-hidden="true" />
                        <span className="truncate text-neutral-300 text-[11px]" title={occ.rawTitle}>
                          {occ.rawTitle || occ.sourceFeedName}
                        </span>
                      </div>

                      <div className="flex items-center gap-1 shrink-0 ml-2">
                        {occ.quality && (
                          <span
                            data-testid="quality-badge"
                            className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-neutral-800 text-blue-300 border border-neutral-700"
                          >
                            {occ.quality}
                          </span>
                        )}
                        {occ.ripType && (
                          <span
                            data-testid="riptype-badge"
                            className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-neutral-800 text-neutral-300 border border-neutral-700"
                          >
                            {occ.ripType}
                          </span>
                        )}
                      </div>
                    </a>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-neutral-500 py-1 text-center">No torrent links available</div>
              )}
            </div>
          )}

          <div className="text-[10px] text-neutral-500 flex justify-between items-center pt-1">
            <span>First seen: {new Date(title.firstSeenAt).toLocaleDateString()}</span>
            <span className="font-mono text-neutral-600 truncate max-w-[100px]" title={title.id}>
              {title.id}
            </span>
          </div>
        </div>
      </article>

      {/* Full Movie Information Modal */}
      <TitleDetailModal
        title={currentTitle}
        isOpen={isDetailModalOpen}
        onClose={() => setIsDetailModalOpen(false)}
        repository={repository}
        initialOccurrences={occurrences}
      />
    </>
  );
};
