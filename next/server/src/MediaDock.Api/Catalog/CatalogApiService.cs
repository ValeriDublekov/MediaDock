using MediaDock.Api.Common;
using MediaDock.Api.Middleware;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.Api.Catalog;

internal interface ICatalogApiService
{
    Task<PageResponse<CatalogTitleResponse>> GetCatalogAsync(
        CatalogQuery query,
        CancellationToken cancellationToken);

    Task<TitleDetailsResponse> GetTitleAsync(long id, CancellationToken cancellationToken);

    Task<PageResponse<OccurrenceResponse>> GetOccurrencesAsync(
        long titleId,
        OccurrencesQuery query,
        CancellationToken cancellationToken);
}

internal sealed class CatalogApiService(MediaDockDbContext dbContext) : ICatalogApiService
{
    public async Task<PageResponse<CatalogTitleResponse>> GetCatalogAsync(
        CatalogQuery query,
        CancellationToken cancellationToken)
    {
        var page = query.Page ?? 1;
        var pageSize = query.PageSize ?? 25;
        if (query.YearFrom is { } yearFrom && query.YearTo is { } yearTo && yearFrom > yearTo)
        {
            throw new ApiValidationException(new Dictionary<string, string[]>
            {
                [nameof(query.YearTo)] = ["YearTo must be greater than or equal to YearFrom."]
            });
        }

        IQueryable<Title> titles = dbContext.Titles
            .AsNoTracking()
            .Where(title => title.Occurrences.Any());

        if (!string.IsNullOrWhiteSpace(query.Search))
        {
            var pattern = $"%{query.Search.Trim()}%";
            titles = titles.Where(title => EF.Functions.ILike(title.TitleText, pattern)
                || EF.Functions.ILike(title.NormalizedTitle, pattern));
        }

        if (query.MediaType is not null)
        {
            titles = titles.Where(title => title.MediaType == query.MediaType);
        }

        if (query.SourceType is not null)
        {
            titles = titles.Where(title => title.SourceType == query.SourceType);
        }

        if (query.ContentKind is not null)
        {
            titles = titles.Where(title => title.ContentKind == query.ContentKind);
        }

        if (query.YearFrom is { } minimumYear)
        {
            titles = titles.Where(title => title.Year >= minimumYear);
        }

        if (query.YearTo is { } maximumYear)
        {
            titles = titles.Where(title => title.Year <= maximumYear);
        }

        if (!string.IsNullOrWhiteSpace(query.Genre))
        {
            var genre = query.Genre.Trim();
            titles = titles.Where(title => title.Genres.Contains(genre));
        }

        if (!string.IsNullOrWhiteSpace(query.Country))
        {
            var country = query.Country.Trim();
            titles = titles.Where(title => title.Countries.Contains(country));
        }

        if (query.SourceId is { } sourceId)
        {
            titles = titles.Where(title => title.Occurrences.Any(occurrence => occurrence.SourceId == sourceId));
        }

        var totalCount = await titles.CountAsync(cancellationToken);
        var items = await titles
            .OrderByDescending(title => title.LastSeenAt)
            .ThenByDescending(title => title.Id)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(title => new CatalogTitleResponse(
                title.Id,
                title.TitleText,
                title.Year,
                title.MediaType,
                title.SourceType,
                title.ContentKind,
                title.ImdbRating,
                title.PosterUrl,
                title.Genres,
                title.Countries,
                title.LastSeenAt,
                title.Occurrences.Count))
            .ToListAsync(cancellationToken);

        return CreatePage(items, page, pageSize, totalCount);
    }

    public async Task<TitleDetailsResponse> GetTitleAsync(long id, CancellationToken cancellationToken)
    {
        var title = await dbContext.Titles
            .AsNoTracking()
            .Where(entity => entity.Id == id)
            .Select(entity => new TitleDetailsResponse(
                entity.Id,
                entity.TitleText,
                entity.Year,
                entity.MediaType,
                entity.SourceType,
                entity.ContentKind,
                entity.BroadcastRangeStartYear,
                entity.BroadcastRangeEndYear,
                entity.BroadcastRangeRaw,
                entity.ImdbId,
                entity.ImdbRating,
                entity.ImdbVotes,
                entity.Metascore,
                entity.Genres,
                entity.Countries,
                entity.Director,
                entity.Plot,
                entity.PosterUrl,
                entity.Runtime,
                entity.Awards,
                entity.BoxOffice,
                entity.FirstSeenAt,
                entity.LastSeenAt,
                entity.UpdatedAt,
                entity.Occurrences.Count))
            .FirstOrDefaultAsync(cancellationToken);

        return title ?? throw new ApiNotFoundException("Title not found.");
    }

    public async Task<PageResponse<OccurrenceResponse>> GetOccurrencesAsync(
        long titleId,
        OccurrencesQuery query,
        CancellationToken cancellationToken)
    {
        var page = query.Page ?? 1;
        var pageSize = query.PageSize ?? 25;
        var titleExists = await dbContext.Titles.AnyAsync(title => title.Id == titleId, cancellationToken);
        if (!titleExists)
        {
            throw new ApiNotFoundException("Title not found.");
        }

        var occurrences = dbContext.Occurrences
            .AsNoTracking()
            .Where(occurrence => occurrence.TitleId == titleId);
        var totalCount = await occurrences.CountAsync(cancellationToken);
        var items = await occurrences
            .OrderByDescending(occurrence => occurrence.LastSeenAt)
            .ThenByDescending(occurrence => occurrence.Id)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(occurrence => new OccurrenceResponse(
                occurrence.Id,
                occurrence.TitleId,
                occurrence.SourceId,
                occurrence.Source.Name,
                occurrence.SourceItemKey,
                occurrence.FeedEntryId,
                occurrence.TorrentUrl,
                occurrence.RawTitle,
                occurrence.SourceFeedName,
                occurrence.FeedType,
                occurrence.SourcePublishedAt,
                occurrence.ObservedAt,
                occurrence.Quality,
                occurrence.RipType,
                occurrence.FirstSeenAt,
                occurrence.LastSeenAt))
            .ToListAsync(cancellationToken);

        return CreatePage(items, page, pageSize, totalCount);
    }

    private static PageResponse<T> CreatePage<T>(IReadOnlyList<T> items, int page, int pageSize, int totalCount) =>
        new(items, page, pageSize, totalCount, totalCount == 0 ? 0 : (totalCount + pageSize - 1) / pageSize);
}