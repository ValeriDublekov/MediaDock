using MediaDock.Application.Ingestion;

namespace MediaDock.Infrastructure.Persistence;

public static class SourceItemKey
{
    public static string From(string? feedEntryId, string? torrentUrl)
    {
        return SourceItemIdentity.From(feedEntryId, torrentUrl);
    }
}