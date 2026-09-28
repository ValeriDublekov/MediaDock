using System.Xml;

namespace MediaDock.Infrastructure.Rss;

internal static class RssFeedXmlValidator
{
    public static void Validate(byte[] body, int maxEntries)
    {
        var settings = new XmlReaderSettings
        {
            DtdProcessing = DtdProcessing.Prohibit,
            XmlResolver = null,
            MaxCharactersInDocument = Math.Max(1, body.Length),
            MaxCharactersFromEntities = 0,
            ConformanceLevel = ConformanceLevel.Document
        };
        var ancestors = new List<(string Name, string Namespace)>();
        var rootName = string.Empty;
        var rootNamespace = string.Empty;
        var isRss = false;
        var isAtom = false;
        var hasChannel = false;
        var entryCount = 0;

        try
        {
            using var stream = new MemoryStream(body, writable: false);
            using var reader = XmlReader.Create(stream, settings);
            while (reader.Read())
            {
                if (reader.NodeType != XmlNodeType.Element)
                {
                    continue;
                }

                if (reader.Depth < ancestors.Count)
                {
                    ancestors.RemoveRange(reader.Depth, ancestors.Count - reader.Depth);
                }

                if (reader.Depth == 0)
                {
                    rootName = reader.LocalName;
                    rootNamespace = reader.NamespaceURI;
                    isRss = rootName == "rss";
                    isAtom = rootName == "feed";
                    if (!isRss && !isAtom)
                    {
                        throw new RssFeedFormatException("response is not an RSS or Atom feed");
                    }
                }
                else if (ancestors.Count == reader.Depth)
                {
                    var parent = ancestors[reader.Depth - 1];
                    if (isRss
                        && reader.Depth == 1
                        && parent.Name == rootName
                        && parent.Namespace == rootNamespace
                        && reader.LocalName == "channel"
                        && reader.NamespaceURI == rootNamespace)
                    {
                        hasChannel = true;
                    }

                    if (isRss
                        && reader.Depth == 2
                        && parent.Name == "channel"
                        && parent.Namespace == rootNamespace
                        && reader.LocalName == "item"
                        && reader.NamespaceURI == rootNamespace)
                    {
                        entryCount++;
                    }

                    if (isAtom
                        && reader.Depth == 1
                        && parent.Name == rootName
                        && parent.Namespace == rootNamespace
                        && reader.LocalName == "entry"
                        && reader.NamespaceURI == rootNamespace)
                    {
                        entryCount++;
                    }

                    if (entryCount > maxEntries)
                    {
                        throw new RssFeedEntryLimitException("feed entry limit exceeded");
                    }
                }

                if (!reader.IsEmptyElement)
                {
                    ancestors.Add((reader.LocalName, reader.NamespaceURI));
                }
            }
        }
        catch (XmlException exception)
        {
            throw new RssFeedFormatException("feed XML is malformed or incomplete", exception);
        }

        if ((!isRss && !isAtom) || (isRss && !hasChannel))
        {
            throw new RssFeedFormatException("response is not a complete RSS or Atom feed");
        }
    }
}