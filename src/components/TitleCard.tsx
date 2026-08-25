import React, { useState, useEffect } from 'react';
import { Title, Occurrence, CatalogRepository } from '../domain/catalog';
import { firestoreCatalogAdapter } from '../adapters/firestoreCatalogAdapter';
import { PosterImage } from './PosterImage';
import { TitleDetailModal } from './TitleDetailModal';
import { Star, ExternalLink, Download, Film, Layers, Award, Clock, Globe, Info, EyeOff } from 'lucide-react';

interface TitleCardProps {
  title: Title;
  repository?: CatalogRepository;
  occurrences?: Occurrence[];
  isFavorite?: boolean;
  isIgnored?: boolean;
  onToggleFavorite?: (titleId: string) => void;
  onToggleIgnored?: (titleId: string) => void;
}

export const TitleCard: React.FC<TitleCardProps> = ({
  title,
  repository = firestoreCatalogAdapter,
  occurrences: initialOccurrences,
  isFavorite = false,
  isIgnored = false,
  onToggleFavorite,
  onToggleIgnored,
}) => {
  const [currentTitle, setCurrentTitle] = useState<Title>(title);
  const [occurrences, setOccurrences] = useState<Occurrence[] | undefined>(initialOccurrences);
  const [isLoadingOccurrences, setIsLoadingOccurrences] = useState(false);
  const [showOccurrences, setShowOccurrences] = useState(false);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);

  useEffect(() => {
    setCurrentTitle(title);
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
        className={`bg-neutral-900 border rounded-xl overflow-hidden shadow-sm hover:border-neutral-700 transition-all flex flex-col justify-between group focus-within:ring-2 focus-within:ring-amber-500/50 ${
          isFavorite
            ? 'border-amber-500/60 shadow-amber-500/10'
            : isIgnored
            ? 'border-red-900/60 opacity-85'
            : 'border-neutral-800'
        }`}
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

            {/* Top Left Badges Overlay */}
            <div className="absolute top-3 left-3 z-10 flex flex-wrap items-center gap-1.5">
              <span
                data-testid="media-type-badge"
                className={`inline-block text-[11px] font-bold px-2.5 py-0.5 rounded-md border backdrop-blur-md shadow-xs ${mediaTypeInfo.className}`}
              >
                {mediaTypeInfo.label}
              </span>
              {isFavorite && (
                <span
                  data-testid="favorite-badge"
                  className="inline-flex items-center gap-1 text-[11px] font-extrabold px-2 py-0.5 rounded-md bg-amber-500 text-neutral-950 border border-amber-400 shadow-md"
                >
                  <Star className="w-3 h-3 fill-neutral-950 text-neutral-950" />
                  Любим
                </span>
              )}
              {isIgnored && (
                <span
                  data-testid="ignored-badge"
                  className="inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded-md bg-red-950/90 text-red-300 border border-red-800 backdrop-blur-md shadow-md"
                >
                  <EyeOff className="w-3 h-3" />
                  Скрит
                </span>
              )}
            </div>

            {/* Top Right Actions & Rating Overlay */}
            <div className="absolute top-3 right-3 z-10 flex items-center gap-1.5">
              {onToggleFavorite && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleFavorite(currentTitle.id);
                  }}
                  data-testid="favorite-button"
                  title={isFavorite ? 'Премахни от любими' : 'Маркирай като любим'}
                  className={`w-8 h-8 rounded-lg flex items-center justify-center border backdrop-blur-md transition-all cursor-pointer ${
                    isFavorite
                      ? 'bg-amber-500 text-neutral-950 border-amber-400 shadow-md'
                      : 'bg-neutral-950/80 hover:bg-neutral-900 text-neutral-400 hover:text-amber-400 border-neutral-800 hover:border-amber-500/50'
                  }`}
                >
                  <Star className={`w-4 h-4 ${isFavorite ? 'fill-neutral-950' : ''}`} />
                </button>
              )}

              {onToggleIgnored && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleIgnored(currentTitle.id);
                  }}
                  data-testid="ignore-button"
                  title={isIgnored ? 'Възстанови от скрити' : 'Скрий (Игнорирай)'}
                  className={`w-8 h-8 rounded-lg flex items-center justify-center border backdrop-blur-md transition-all cursor-pointer ${
                    isIgnored
                      ? 'bg-red-900/90 text-red-200 border-red-700 shadow-md'
                      : 'bg-neutral-950/80 hover:bg-neutral-900 text-neutral-400 hover:text-red-400 border-neutral-800 hover:border-red-500/50'
                  }`}
                >
                  <EyeOff className="w-4 h-4" />
                </button>
              )}

              {currentTitle.imdbRating !== null && currentTitle.imdbRating !== undefined && (
                <div
                  data-testid="rating-badge"
                  className="bg-neutral-950/90 backdrop-blur-md border border-amber-500/40 text-amber-400 text-xs font-bold px-2.5 py-1 rounded-md flex items-center gap-1 shadow-md"
                  aria-label={`IMDb Rating: ${currentTitle.imdbRating} out of 10`}
                >
                  <Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" aria-hidden="true" />
                  <span>{currentTitle.imdbRating.toFixed(1)}</span>
                </div>
              )}
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
        isFavorite={isFavorite}
        isIgnored={isIgnored}
        onToggleFavorite={onToggleFavorite}
        onToggleIgnored={onToggleIgnored}
      />
    </>
  );
};
