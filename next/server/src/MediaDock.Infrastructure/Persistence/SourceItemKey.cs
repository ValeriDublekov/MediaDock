namespace MediaDock.Infrastructure.Persistence;

public static class SourceItemKey
{
    public static string From(string? feedEntryId, string? torrentUrl)
    {
        if (!string.IsNullOrWhiteSpace(feedEntryId))
        {
            return $"entry:{feedEntryId.Trim()}";
        }

        if (!string.IsNullOrWhiteSpace(torrentUrl))
        {
            return $"url:{torrentUrl.Trim()}";
        }

        throw new ArgumentException("A feed entry ID or torrent URL is required.", nameof(feedEntryId));
    }
}