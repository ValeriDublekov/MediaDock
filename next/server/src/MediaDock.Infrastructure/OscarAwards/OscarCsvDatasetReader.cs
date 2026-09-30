using System.Globalization;
using System.Text;
using MediaDock.Application.Metadata;
using Microsoft.VisualBasic.FileIO;

namespace MediaDock.Infrastructure.OscarAwards;

internal sealed record OscarDatasetRow(
    int Ceremony,
    int FilmYear,
    string Class,
    string CanonicalCategory,
    string Category,
    string FilmTitle,
    string? ImdbId,
    string Name,
    string Nominees,
    string NomineeIds,
    string Detail,
    bool IsWinner);

internal sealed record OscarCsvReadResult(
    IReadOnlyList<OscarDatasetRow> Rows,
    int RowsRead,
    int RowsSkippedByYear,
    int RowsSkippedByCategory,
    int RowsSkippedWithoutFilm);

internal static class OscarCsvDatasetReader
{
    private static readonly HashSet<string> TargetCategories = new(StringComparer.OrdinalIgnoreCase)
    {
        "BEST PICTURE",
        "DIRECTING",
        "WRITING (Original Screenplay)",
        "WRITING (Adapted Screenplay)",
        "CINEMATOGRAPHY"
    };

    private static readonly string[] RequiredColumns =
    [
        "Ceremony",
        "Year",
        "Class",
        "CanonicalCategory",
        "Category",
        "Film"
    ];

    public static OscarCsvReadResult Read(
        string path,
        int yearAfter,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(path))
        {
            throw new FileNotFoundException("Oscar dataset file was not found.", path);
        }

        using var parser = new TextFieldParser(path, Encoding.UTF8, detectEncoding: true)
        {
            TextFieldType = FieldType.Delimited,
            HasFieldsEnclosedInQuotes = true,
            TrimWhiteSpace = false
        };
        parser.SetDelimiters(DetectDelimiter(path));

        var rawHeaders = parser.ReadFields()
            ?? throw new InvalidDataException("Oscar dataset has no header row.");
        var headers = rawHeaders.Select(header => header.Trim().TrimStart('\uFEFF')).ToArray();
        var columnIndexes = headers
            .Select((header, index) => (header, index))
            .ToDictionary(item => item.header, item => item.index, StringComparer.OrdinalIgnoreCase);
        var missingColumns = RequiredColumns
            .Where(column => !columnIndexes.ContainsKey(column))
            .ToArray();
        if (missingColumns.Length > 0)
        {
            throw new InvalidDataException(
                $"Oscar dataset is missing required columns: {string.Join(", ", missingColumns)}.");
        }

        var rows = new List<OscarDatasetRow>();
        var rowsRead = 0;
        var rowsSkippedByYear = 0;
        var rowsSkippedByCategory = 0;
        var rowsSkippedWithoutFilm = 0;
        while (!parser.EndOfData)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var fields = parser.ReadFields();
            if (fields is null)
            {
                continue;
            }

            rowsRead++;
            if (fields.Length != headers.Length)
            {
                throw new InvalidDataException(
                    $"Oscar dataset row {parser.LineNumber} has {fields.Length} fields; expected {headers.Length}.");
            }

            var yearText = ReadField(fields, columnIndexes, "Year");
            if (!int.TryParse(yearText, NumberStyles.None, CultureInfo.InvariantCulture, out var filmYear)
                || filmYear <= yearAfter)
            {
                rowsSkippedByYear++;
                continue;
            }

            var canonicalCategory = ReadField(fields, columnIndexes, "CanonicalCategory");
            if (!TargetCategories.Contains(canonicalCategory))
            {
                rowsSkippedByCategory++;
                continue;
            }

            var filmTitle = ReadField(fields, columnIndexes, "Film");
            if (string.IsNullOrWhiteSpace(filmTitle))
            {
                rowsSkippedWithoutFilm++;
                continue;
            }

            var ceremonyText = ReadField(fields, columnIndexes, "Ceremony");
            if (!int.TryParse(ceremonyText, NumberStyles.None, CultureInfo.InvariantCulture, out var ceremony))
            {
                throw new InvalidDataException(
                    $"Oscar dataset row {parser.LineNumber} has an invalid Ceremony value.");
            }

            rows.Add(new OscarDatasetRow(
                ceremony,
                filmYear,
                ReadField(fields, columnIndexes, "Class"),
                canonicalCategory,
                ReadField(fields, columnIndexes, "Category"),
                filmTitle,
                ImdbIdNormalizer.Normalize(NullIfEmpty(ReadField(fields, columnIndexes, "FilmId"))),
                ReadField(fields, columnIndexes, "Name"),
                ReadField(fields, columnIndexes, "Nominees"),
                ReadField(fields, columnIndexes, "NomineeIds"),
                ReadField(fields, columnIndexes, "Detail"),
                ParseWinner(ReadField(fields, columnIndexes, "Winner"))));
        }

        return new OscarCsvReadResult(
            rows,
            rowsRead,
            rowsSkippedByYear,
            rowsSkippedByCategory,
            rowsSkippedWithoutFilm);
    }

    private static string DetectDelimiter(string path)
    {
        using var reader = new StreamReader(path, Encoding.UTF8, detectEncodingFromByteOrderMarks: true);
        var header = reader.ReadLine() ?? string.Empty;
        return header.Count(character => character == '\t') > header.Count(character => character == ',')
            ? "\t"
            : ",";
    }

    private static string ReadField(
        string[] fields,
        IReadOnlyDictionary<string, int> columnIndexes,
        string column) =>
        columnIndexes.TryGetValue(column, out var index) ? fields[index].Trim() : string.Empty;

    private static string? NullIfEmpty(string value) =>
        string.IsNullOrWhiteSpace(value) || string.Equals(value, "N/A", StringComparison.OrdinalIgnoreCase)
            ? null
            : value;

    private static bool ParseWinner(string value) =>
        string.Equals(value, "true", StringComparison.OrdinalIgnoreCase)
        || string.Equals(value, "yes", StringComparison.OrdinalIgnoreCase)
        || value == "1";
}