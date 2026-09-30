using MediaDock.Api.Common;
using MediaDock.Api.Middleware;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.Api.OscarAwards;

internal interface IOscarApiService
{
    Task<PageResponse<OscarFilmResponse>> GetOscarFilmsAsync(
        OscarCatalogQuery query,
        CancellationToken cancellationToken);

    Task<OscarFilmResponse> GetOscarFilmAsync(long id, CancellationToken cancellationToken);
}

internal sealed class OscarApiService(MediaDockDbContext dbContext) : IOscarApiService
{
    public async Task<PageResponse<OscarFilmResponse>> GetOscarFilmsAsync(
        OscarCatalogQuery query,
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

        IQueryable<OscarFilm> films = dbContext.OscarFilms.AsNoTracking();
        if (!string.IsNullOrWhiteSpace(query.Search))
        {
            var pattern = $"%{query.Search.Trim()}%";
            films = films.Where(film => EF.Functions.ILike(film.FilmTitle, pattern)
                || EF.Functions.ILike(film.NormalizedTitle, pattern)
                || EF.Functions.ILike(film.Title.TitleText, pattern)
                || EF.Functions.ILike(film.Title.NormalizedTitle, pattern));
        }

        if (query.YearFrom is { } minimumYear)
        {
            films = films.Where(film => film.FilmYear >= minimumYear);
        }

        if (query.YearTo is { } maximumYear)
        {
            films = films.Where(film => film.FilmYear <= maximumYear);
        }

        var category = string.IsNullOrWhiteSpace(query.Category)
            ? null
            : query.Category.Trim().ToUpperInvariant();
        var result = query.Result;
        if (category is not null || result is not null)
        {
            films = films.Where(film => film.Nominations.Any(nomination =>
                (category == null || nomination.CanonicalCategory.ToUpper() == category)
                && (result == null
                    || (result == "winner" && nomination.IsWinner)
                    || (result == "nominee" && !nomination.IsWinner))));
        }

        if (!string.IsNullOrWhiteSpace(query.EnrichmentStatus))
        {
            films = films.Where(film => film.EnrichmentStatus == query.EnrichmentStatus);
        }

        var totalCount = await films.CountAsync(cancellationToken);
        var items = await films
            .Include(film => film.Title)
            .Include(film => film.Nominations)
            .OrderByDescending(film => film.FilmYear)
            .ThenBy(film => film.NormalizedTitle)
            .ThenBy(film => film.Id)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .ToListAsync(cancellationToken);

        return CreatePage(items.Select(ToResponse).ToArray(), page, pageSize, totalCount);
    }

    public async Task<OscarFilmResponse> GetOscarFilmAsync(long id, CancellationToken cancellationToken)
    {
        var film = await dbContext.OscarFilms
            .AsNoTracking()
            .Include(candidate => candidate.Title)
            .Include(candidate => candidate.Nominations)
            .FirstOrDefaultAsync(candidate => candidate.Id == id, cancellationToken);

        return film is null
            ? throw new ApiNotFoundException("Oscar film not found.")
            : ToResponse(film);
    }

    private static OscarFilmResponse ToResponse(OscarFilm film) => new(
        film.Id,
        film.TitleId,
        film.FilmTitle,
        film.Title.TitleText,
        film.Title.Year,
        film.FilmYear,
        film.ImdbId ?? film.Title.ImdbId,
        film.EnrichmentStatus,
        film.EnrichmentAttemptCount,
        film.LastEnrichmentAttemptAt,
        film.NextEnrichmentAttemptAt,
        film.LastEnrichmentError,
        film.Title.MediaType,
        film.Title.ImdbRating,
        film.Title.ImdbVotes,
        film.Title.Metascore,
        film.Title.Genres,
        film.Title.Countries,
        film.Title.Director,
        film.Title.Plot,
        film.Title.PosterUrl,
        film.Title.Runtime,
        film.Title.Awards,
        film.Title.BoxOffice,
        film.Nominations
            .OrderBy(nomination => nomination.Ceremony)
            .ThenBy(nomination => nomination.CanonicalCategory)
            .ThenBy(nomination => nomination.Id)
            .Select(nomination => new OscarNominationResponse(
                nomination.Id,
                nomination.Ceremony,
                nomination.Class,
                nomination.CanonicalCategory,
                nomination.Category,
                nomination.Name,
                nomination.Nominees,
                nomination.NomineeIds,
                nomination.Detail,
                nomination.IsWinner))
            .ToArray());

    private static PageResponse<T> CreatePage<T>(IReadOnlyList<T> items, int page, int pageSize, int totalCount) =>
        new(items, page, pageSize, totalCount, totalCount == 0 ? 0 : (totalCount + pageSize - 1) / pageSize);
}