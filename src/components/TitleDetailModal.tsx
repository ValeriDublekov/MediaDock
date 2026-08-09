import React, { useState, useEffect } from 'react';
import { Title, Occurrence, CatalogRepository } from '../domain/catalog';
import { firestoreCatalogAdapter } from '../adapters/firestoreCatalogAdapter';
import { updateTitleWithOmdb } from '../adapters/omdbAdapter';
import { PosterImage } from './PosterImage';
import {
  Star,
  ExternalLink,
  Download,
  Award,
  Clock,
  Globe,
  RefreshCw,
  Edit2,
  Check,
  X,
  Loader2,
  DollarSign,
  User,
  Film,
  Calendar,
  Layers,
  Sparkles,
} from 'lucide-react';

interface TitleDetailModalProps {
  title: Title;
  isOpen: boolean;
  onClose: () => void;
  repository?: CatalogRepository;
  initialOccurrences?: Occurrence[];
}

export const TitleDetailModal: React.FC<TitleDetailModalProps> = ({
  title,
  isOpen,
  onClose,
  repository = firestoreCatalogAdapter,
  initialOccurrences,
}) => {
  const [currentTitle, setCurrentTitle] = useState<Title>(title);
  const [occurrences, setOccurrences] = useState<Occurrence[] | undefined>(initialOccurrences);
  const [isLoadingOccurrences, setIsLoadingOccurrences] = useState(false);
  const [isEditingId, setIsEditingId] = useState(false);
  const [editImdbId, setEditImdbId] = useState(title.imdbId || '');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  useEffect(() => {
    setCurrentTitle(title);
    setEditImdbId(title.imdbId || '');
  }, [title]);

  // Handle ESC key press to close modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Fetch occurrences on modal open if not already loaded
  useEffect(() => {
    let isMounted = true;
    if (isOpen && repository && !occurrences && !initialOccurrences) {
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
  }, [isOpen, initialOccurrences, repository, currentTitle.id, occurrences]);

  if (!isOpen) return null;

  const handleRefreshOmdb = async (targetImdbId?: string) => {
    const apiKey =
      localStorage.getItem('movies_feed_omdb_api_key') ||
      import.meta.env.VITE_OMDB_API_KEY ||
      import.meta.env.OMDB_API_KEY;
    if (!apiKey) {
      setRefreshError('Missing OMDb API Key. Set it in Scanner Settings or LocalStorage.');
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

  const formatMediaType = (type: string) => {
    const lower = type.toLowerCase();
    if (lower === 'movie')
      return { label: 'Movie', className: 'bg-neutral-800 text-neutral-200 border-neutral-700' };
    if (lower === 'series' || lower === 'tv series')
      return { label: 'TV Series', className: 'bg-emerald-950 text-emerald-300 border-emerald-800' };
    if (lower === 'documentary')
      return { label: 'Documentary', className: 'bg-sky-950 text-sky-300 border-sky-800' };
    if (lower === 'short' || lower === 'short movie')
      return { label: 'Short Movie', className: 'bg-purple-950 text-purple-300 border-purple-800' };
    return { label: type, className: 'bg-neutral-800 text-neutral-300 border-neutral-700' };
  };

  const mediaTypeInfo = formatMediaType(currentTitle.mediaType);

  const formatVotes = (votes: number | null | undefined) => {
    if (!votes) return null;
    return votes.toLocaleString();
  };

  return (
    <div
      data-testid="title-detail-backdrop"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md animate-in fade-in duration-200 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="detail-modal-title"
    >
      <div
        data-testid="title-detail-modal"
        onClick={(e) => e.stopPropagation()}
        className="relative w-full max-w-3xl bg-neutral-900 border border-neutral-800 rounded-2xl shadow-2xl overflow-hidden my-auto max-h-[92vh] flex flex-col text-neutral-100"
      >
        {/* Header Bar */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-neutral-800 bg-neutral-950/80 shrink-0">
          <div className="flex items-center gap-2.5 overflow-hidden">
            <span
              className={`inline-block text-xs font-bold px-2.5 py-0.5 rounded-md border shrink-0 ${mediaTypeInfo.className}`}
            >
              {mediaTypeInfo.label}
            </span>
            <h2
              id="detail-modal-title"
              data-testid="detail-modal-title"
              className="text-lg font-bold text-neutral-100 truncate"
              title={currentTitle.title}
            >
              {currentTitle.title}
            </h2>
            {currentTitle.year && (
              <span className="text-xs font-semibold px-2 py-0.5 rounded bg-neutral-800 text-neutral-300 border border-neutral-700 shrink-0">
                {currentTitle.year}
              </span>
            )}
          </div>

          <button
            onClick={onClose}
            data-testid="close-detail-modal-button"
            className="w-9 h-9 rounded-xl text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800 flex items-center justify-center transition-colors shrink-0 cursor-pointer"
            aria-label="Close details modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Scrollable Content Body */}
        <div className="p-5 sm:p-6 space-y-6 overflow-y-auto flex-1">
          {/* Main Showcase Layout: Poster + Key Details */}
          <div className="grid grid-cols-1 sm:grid-cols-12 gap-6 items-start">
            {/* Poster Column */}
            <div className="sm:col-span-4 flex flex-col items-center">
              <div className="relative aspect-[2/3] w-full max-w-[240px] sm:max-w-none rounded-xl overflow-hidden bg-neutral-950 border border-neutral-800 shadow-lg">
                <PosterImage
                  posterUrl={currentTitle.posterUrl}
                  title={currentTitle.title}
                  className="w-full h-full object-cover"
                />
                {currentTitle.imdbRating !== null && currentTitle.imdbRating !== undefined && (
                  <div className="absolute top-3 right-3 bg-neutral-950/90 backdrop-blur-md border border-amber-500/40 text-amber-400 text-xs font-bold px-2.5 py-1 rounded-md flex items-center gap-1 shadow-md">
                    <Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
                    <span>{currentTitle.imdbRating.toFixed(1)} / 10</span>
                  </div>
                )}
              </div>

              {/* Action Buttons below poster */}
              <div className="w-full mt-4 space-y-2">
                {currentTitle.imdbId ? (
                  <a
                    href={`https://www.imdb.com/title/${currentTitle.imdbId}/`}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="detail-modal-imdb-link"
                    className="w-full min-h-[44px] px-4 py-2.5 text-xs font-bold rounded-xl bg-amber-500 hover:bg-amber-400 text-neutral-950 flex items-center justify-center gap-2 transition-colors shadow-sm cursor-pointer"
                  >
                    <ExternalLink className="w-4 h-4" />
                    <span>Open on IMDb</span>
                  </a>
                ) : (
                  <div className="text-center text-xs text-neutral-500 italic py-2">No IMDb Link</div>
                )}

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setIsEditingId(!isEditingId)}
                    className="flex-1 min-h-[40px] px-3 py-2 text-xs font-medium rounded-xl bg-neutral-800 hover:bg-neutral-700 text-neutral-300 border border-neutral-700 flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                    <span>Edit IMDb ID</span>
                  </button>

                  {currentTitle.imdbId && (
                    <button
                      type="button"
                      onClick={() => handleRefreshOmdb()}
                      disabled={isRefreshing}
                      className="min-h-[40px] px-3 py-2 text-xs font-medium rounded-xl bg-neutral-800 hover:bg-neutral-700 text-neutral-300 border border-neutral-700 flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50 cursor-pointer"
                      title="Refresh metadata from OMDb"
                    >
                      {isRefreshing ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-400" />
                      ) : (
                        <RefreshCw className="w-3.5 h-3.5 text-amber-400" />
                      )}
                      <span>Refresh</span>
                    </button>
                  )}
                </div>

                {isEditingId && (
                  <div className="p-3 bg-neutral-950 border border-neutral-800 rounded-xl space-y-2 mt-2">
                    <label className="block text-[11px] font-semibold text-neutral-400">IMDb ID:</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={editImdbId}
                        onChange={(e) => setEditImdbId(e.target.value)}
                        placeholder="tt1234567"
                        className="flex-1 px-2.5 py-1.5 bg-neutral-900 border border-neutral-700 rounded-lg text-xs font-mono text-neutral-100"
                      />
                      <button
                        onClick={() => handleRefreshOmdb(editImdbId)}
                        disabled={!editImdbId || isRefreshing}
                        className="px-3 py-1.5 bg-amber-500 hover:bg-amber-400 text-neutral-950 rounded-lg text-xs font-semibold flex items-center gap-1"
                      >
                        {isRefreshing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                      </button>
                      <button
                        onClick={() => setIsEditingId(false)}
                        className="px-2.5 py-1.5 bg-neutral-800 text-neutral-300 rounded-lg text-xs"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                )}

                {refreshError && (
                  <div className="text-xs text-red-400 bg-red-950/50 p-2.5 rounded-xl border border-red-900/60">
                    {refreshError}
                  </div>
                )}
              </div>
            </div>

            {/* Info Column */}
            <div className="sm:col-span-8 space-y-4">
              {/* Quick Info Grid */}
              <div className="grid grid-cols-2 gap-3 text-xs">
                {currentTitle.director && (
                  <div className="p-3 rounded-xl bg-neutral-950/80 border border-neutral-800/80 space-y-1">
                    <span className="text-[11px] font-medium text-neutral-400 flex items-center gap-1.5">
                      <User className="w-3.5 h-3.5 text-amber-400" /> Director
                    </span>
                    <p className="font-semibold text-neutral-200" data-testid="detail-modal-director">{currentTitle.director}</p>
                  </div>
                )}

                {currentTitle.runtime && (
                  <div className="p-3 rounded-xl bg-neutral-950/80 border border-neutral-800/80 space-y-1">
                    <span className="text-[11px] font-medium text-neutral-400 flex items-center gap-1.5">
                      <Clock className="w-3.5 h-3.5 text-amber-400" /> Runtime
                    </span>
                    <p className="font-semibold text-neutral-200" data-testid="detail-modal-runtime">{currentTitle.runtime}</p>
                  </div>
                )}

                {currentTitle.countries && currentTitle.countries.length > 0 && (
                  <div className="p-3 rounded-xl bg-neutral-950/80 border border-neutral-800/80 space-y-1">
                    <span className="text-[11px] font-medium text-neutral-400 flex items-center gap-1.5">
                      <Globe className="w-3.5 h-3.5 text-amber-400" /> Countries
                    </span>
                    <p className="font-semibold text-neutral-200" data-testid="detail-modal-countries">{currentTitle.countries.join(', ')}</p>
                  </div>
                )}

                {currentTitle.boxOffice && (
                  <div className="p-3 rounded-xl bg-neutral-950/80 border border-neutral-800/80 space-y-1">
                    <span className="text-[11px] font-medium text-neutral-400 flex items-center gap-1.5">
                      <DollarSign className="w-3.5 h-3.5 text-emerald-400" /> Box Office
                    </span>
                    <p className="font-semibold text-emerald-300" data-testid="detail-modal-boxoffice">{currentTitle.boxOffice}</p>
                  </div>
                )}
              </div>

              {/* Genres List */}
              {currentTitle.genres && currentTitle.genres.length > 0 && (
                <div className="space-y-1.5">
                  <span className="text-[11px] uppercase tracking-wider font-bold text-neutral-400">Genres</span>
                  <div className="flex flex-wrap gap-1.5" data-testid="detail-modal-genres">
                    {currentTitle.genres.map((genre) => (
                      <span
                        key={genre}
                        className="text-xs px-2.5 py-1 rounded-lg bg-neutral-800/90 text-neutral-200 border border-neutral-700/80 font-medium"
                      >
                        {genre}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Ratings Scores Section */}
              <div className="space-y-2 pt-2 border-t border-neutral-800/80">
                <span className="text-[11px] uppercase tracking-wider font-bold text-neutral-400">Ratings & Scores</span>
                <div className="flex flex-wrap gap-2 text-xs">
                  {currentTitle.imdbRating !== null && currentTitle.imdbRating !== undefined && (
                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-amber-950/30 border border-amber-900/40 text-amber-300">
                      <Star className="w-4 h-4 text-amber-400 fill-amber-400 shrink-0" />
                      <span className="font-bold">{currentTitle.imdbRating.toFixed(1)}/10</span>
                      {currentTitle.imdbVotes && (
                        <span className="text-[11px] text-amber-400/70 border-l border-amber-800/50 pl-2">
                          {formatVotes(currentTitle.imdbVotes)} votes
                        </span>
                      )}
                    </div>
                  )}

                  {currentTitle.metascore !== null && currentTitle.metascore !== undefined && (
                    <div
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-bold ${
                        currentTitle.metascore >= 60
                          ? 'bg-emerald-950/30 text-emerald-300 border-emerald-800/50'
                          : currentTitle.metascore >= 40
                          ? 'bg-amber-950/30 text-amber-300 border-amber-800/50'
                          : 'bg-red-950/30 text-red-300 border-red-800/50'
                      }`}
                    >
                      <span>Metascore: {currentTitle.metascore}/100</span>
                    </div>
                  )}

                  {currentTitle.ratings &&
                    currentTitle.ratings.map((r, idx) => (
                      <div
                        key={idx}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-neutral-950 border border-neutral-800 text-neutral-300 font-medium"
                      >
                        <span className="text-[11px] text-neutral-400">{r.source}:</span>
                        <span className="font-bold text-neutral-100">{r.value}</span>
                      </div>
                    ))}
                </div>
              </div>

              {/* Plot Overview */}
              {currentTitle.plot && (
                <div className="space-y-1.5 pt-2 border-t border-neutral-800/80">
                  <span className="text-[11px] uppercase tracking-wider font-bold text-neutral-400">Plot Summary</span>
                  <p
                    data-testid="detail-modal-plot"
                    className="text-sm text-neutral-300 leading-relaxed bg-neutral-950/60 p-4 rounded-xl border border-neutral-800/80"
                  >
                    {currentTitle.plot}
                  </p>
                </div>
              )}

              {/* Awards */}
              {currentTitle.awards && (
                <div
                  data-testid="detail-modal-awards"
                  className="flex items-center gap-2.5 text-xs text-amber-300 bg-amber-950/30 border border-amber-900/40 p-3 rounded-xl"
                >
                  <Award className="w-4 h-4 text-amber-400 shrink-0" />
                  <span>{currentTitle.awards}</span>
                </div>
              )}

              {/* Qualities Available */}
              {currentTitle.qualities && currentTitle.qualities.length > 0 && (
                <div className="space-y-1.5">
                  <span className="text-[11px] uppercase tracking-wider font-bold text-neutral-400">Available Qualities</span>
                  <div className="flex flex-wrap gap-1.5">
                    {currentTitle.qualities.map((q) => (
                      <span
                        key={q}
                        className="text-xs px-2.5 py-0.5 rounded-md bg-blue-950 text-blue-300 border border-blue-800/60 font-semibold"
                      >
                        {q}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Torrent Links / Occurrences Section */}
          <div className="space-y-3 pt-4 border-t border-neutral-800">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Download className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-bold text-neutral-100">Torrents & Downloads</h3>
              </div>
              {occurrences && (
                <span className="text-xs text-neutral-400 bg-neutral-800 px-2 py-0.5 rounded-full">
                  {occurrences.length} available
                </span>
              )}
            </div>

            {isLoadingOccurrences ? (
              <div className="flex items-center justify-center py-8 text-neutral-400 gap-2 text-xs animate-pulse">
                <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
                <span>Loading torrent sources...</span>
              </div>
            ) : occurrences && occurrences.length > 0 ? (
              <div className="space-y-2" data-testid="detail-modal-occurrences">
                {occurrences.map((occ) => (
                  <a
                    key={occ.id}
                    href={occ.torrentUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="detail-modal-torrent-link"
                    className="flex flex-col sm:flex-row sm:items-center justify-between p-3.5 rounded-xl bg-neutral-950 hover:bg-neutral-800/80 border border-neutral-800 hover:border-neutral-700 transition-all gap-2 group/torrent"
                  >
                    <div className="flex items-start gap-2.5 overflow-hidden">
                      <Download className="w-4 h-4 text-blue-400 shrink-0 mt-0.5 group-hover/torrent:text-blue-300" />
                      <div className="overflow-hidden">
                        <p className="text-xs font-semibold text-neutral-200 group-hover/torrent:text-amber-400 transition-colors truncate">
                          {occ.rawTitle || currentTitle.title}
                        </p>
                        <p className="text-[11px] text-neutral-400 truncate">
                          Source: {occ.sourceFeedName}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
                      {occ.quality && (
                        <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-neutral-800 text-blue-300 border border-neutral-700">
                          {occ.quality}
                        </span>
                      )}
                      {occ.ripType && (
                        <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-neutral-800 text-neutral-300 border border-neutral-700">
                          {occ.ripType}
                        </span>
                      )}
                      <span className="px-3 py-1.5 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 text-xs font-semibold inline-flex items-center gap-1 transition-colors">
                        Download
                        <ExternalLink className="w-3 h-3" />
                      </span>
                    </div>
                  </a>
                ))}
              </div>
            ) : (
              <div className="text-xs text-neutral-500 py-4 text-center bg-neutral-950/40 rounded-xl border border-neutral-800/60">
                No torrent download links currently indexed for this title.
              </div>
            )}
          </div>
        </div>

        {/* Modal Footer */}
        <div className="px-5 py-3 border-t border-neutral-800 bg-neutral-950/80 flex items-center justify-between text-[11px] text-neutral-500 shrink-0">
          <div>
            <span>First seen: {new Date(currentTitle.firstSeenAt).toLocaleDateString()}</span>
            <span className="mx-2">•</span>
            <span>ID: {currentTitle.id}</span>
          </div>

          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 rounded-lg text-xs font-medium transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
