import React from 'react';

interface CatalogSkeletonProps {
  count?: number;
}

export const CatalogSkeleton: React.FC<CatalogSkeletonProps> = ({ count = 6 }) => {
  return (
    <div
      data-testid="catalog-loading"
      role="status"
      aria-label="Loading catalog..."
      className="space-y-6"
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {Array.from({ length: count }).map((_, idx) => (
          <div
            key={idx}
            data-testid="catalog-skeleton"
            className="bg-neutral-900 border border-neutral-800 rounded-xl overflow-hidden flex flex-col justify-between animate-pulse"
          >
            <div>
              <div className="w-full h-72 bg-neutral-800" />
              <div className="p-4 space-y-3">
                <div className="flex justify-between items-center">
                  <div className="h-5 bg-neutral-800 rounded w-3/4" />
                  <div className="h-4 bg-neutral-800 rounded w-12" />
                </div>
                <div className="flex gap-2">
                  <div className="h-4 bg-neutral-800 rounded w-16" />
                  <div className="h-4 bg-neutral-800 rounded w-24" />
                </div>
                <div className="space-y-1.5">
                  <div className="h-3 bg-neutral-800 rounded w-full" />
                  <div className="h-3 bg-neutral-800 rounded w-5/6" />
                </div>
              </div>
            </div>
            <div className="p-4 pt-0">
              <div className="h-10 bg-neutral-800 rounded-lg w-full" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
