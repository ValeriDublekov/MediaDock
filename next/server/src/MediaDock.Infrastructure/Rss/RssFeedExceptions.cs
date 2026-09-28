namespace MediaDock.Infrastructure.Rss;

public class RssFeedException : Exception
{
    public RssFeedException(string message) : base(message)
    {
    }

    public RssFeedException(string message, Exception innerException) : base(message, innerException)
    {
    }
}

public class RssFeedUrlException : RssFeedException
{
    public RssFeedUrlException(string message) : base(message)
    {
    }

    public RssFeedUrlException(string message, Exception innerException) : base(message, innerException)
    {
    }
}

public sealed class RssFeedDnsException : RssFeedUrlException
{
    public RssFeedDnsException(string message) : base(message)
    {
    }

    public RssFeedDnsException(string message, Exception innerException) : base(message, innerException)
    {
    }
}

public sealed class RssFeedTimeoutException : RssFeedException
{
    public RssFeedTimeoutException(string message, Exception innerException) : base(message, innerException)
    {
    }
}

public class RssFeedResponseException : RssFeedException
{
    public RssFeedResponseException(string message) : base(message)
    {
    }

    public RssFeedResponseException(string message, Exception innerException) : base(message, innerException)
    {
    }
}

public sealed class RssFeedSizeLimitException : RssFeedResponseException
{
    public RssFeedSizeLimitException(string message) : base(message)
    {
    }
}

public sealed class RssFeedEntryLimitException : RssFeedResponseException
{
    public RssFeedEntryLimitException(string message) : base(message)
    {
    }
}

public sealed class RssFeedFormatException : RssFeedResponseException
{
    public RssFeedFormatException(string message) : base(message)
    {
    }

    public RssFeedFormatException(string message, Exception innerException) : base(message, innerException)
    {
    }
}