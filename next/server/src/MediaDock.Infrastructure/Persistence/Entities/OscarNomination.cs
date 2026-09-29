namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class OscarNomination
{
    public long Id { get; set; }
    public long OscarFilmId { get; set; }
    public string ImportKey { get; set; } = string.Empty;
    public int Ceremony { get; set; }
    public string Class { get; set; } = string.Empty;
    public string CanonicalCategory { get; set; } = string.Empty;
    public string Category { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Nominees { get; set; } = string.Empty;
    public string NomineeIds { get; set; } = string.Empty;
    public string Detail { get; set; } = string.Empty;
    public bool IsWinner { get; set; }
    public DateTimeOffset ImportedAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }

    public OscarFilm OscarFilm { get; set; } = null!;
}