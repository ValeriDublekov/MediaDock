using MediaDock.Application.Metadata;
using MediaDock.Infrastructure.Persistence.Entities;

namespace MediaDock.Infrastructure.Metadata;

internal static class TitleMetadataMapper
{
    public static void Apply(
        Title title,
        MetadataDetails metadata,
        DateTimeOffset updatedAt,
        bool updateLastSeenAt = true)
    {
        title.TitleText = metadata.Title;
        title.NormalizedTitle = NormalizeTitle(metadata.Title);
        title.Year = metadata.Year;
        title.MediaType = metadata.MediaType;
        title.SourceType = metadata.SourceType;
        title.ContentKind = metadata.ContentKind;
        title.BroadcastRangeStartYear = metadata.BroadcastRange?.StartYear;
        title.BroadcastRangeEndYear = metadata.BroadcastRange?.EndYear;
        title.BroadcastRangeRaw = metadata.BroadcastRange?.Raw;
        var imdbId = ImdbIdNormalizer.Normalize(metadata.ImdbId);
        if (imdbId is not null)
        {
            title.ImdbId = imdbId;
        }
        title.ImdbRating = metadata.ImdbRating;
        title.ImdbVotes = metadata.ImdbVotes;
        title.Metascore = metadata.Metascore;
        title.Genres = metadata.Genres;
        title.Countries = metadata.Countries;
        title.Director = metadata.Director;
        title.Plot = metadata.Plot;
        title.PosterUrl = metadata.PosterUrl;
        title.Runtime = metadata.Runtime;
        title.Awards = metadata.Awards;
        title.BoxOffice = metadata.BoxOffice;
        if (updateLastSeenAt)
        {
            title.FirstSeenAt ??= updatedAt;
            title.LastSeenAt = updatedAt;
        }

        title.UpdatedAt = updatedAt;
    }

    public static string NormalizeTitle(string title) =>
        string.Join(' ', title.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)).ToLowerInvariant();
}