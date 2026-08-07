import React, { useState } from 'react';
import { Film } from 'lucide-react';

interface PosterImageProps {
  posterUrl?: string | null;
  title: string;
  className?: string;
}

export const PosterImage: React.FC<PosterImageProps> = ({ posterUrl, title, className = '' }) => {
  const [imageError, setImageError] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);

  const hasValidUrl = Boolean(posterUrl && posterUrl.trim() !== '' && posterUrl !== 'N/A');

  if (!hasValidUrl || imageError) {
    return (
      <div
        data-testid="poster-fallback"
        role="img"
        aria-label={`Poster placeholder for ${title}`}
        className={`bg-neutral-900 text-neutral-400 flex flex-col items-center justify-center p-4 text-center select-none ${className}`}
      >
        <Film className="w-10 h-10 mb-2 opacity-40 text-neutral-400" aria-hidden="true" />
        <span className="text-[11px] font-medium text-neutral-500 uppercase tracking-wider">No Poster</span>
      </div>
    );
  }

  return (
    <div className={`relative overflow-hidden bg-neutral-950 ${className}`}>
      {!imageLoaded && (
        <div
          data-testid="poster-skeleton"
          className="absolute inset-0 bg-neutral-800 animate-pulse flex items-center justify-center"
        >
          <Film className="w-8 h-8 text-neutral-700" aria-hidden="true" />
        </div>
      )}
      <img
        src={posterUrl!}
        alt={`${title} poster`}
        referrerPolicy="no-referrer"
        onLoad={() => setImageLoaded(true)}
        onError={() => setImageError(true)}
        className={`w-full h-full object-cover transition-opacity duration-300 ${
          imageLoaded ? 'opacity-100' : 'opacity-0'
        }`}
      />
    </div>
  );
};
