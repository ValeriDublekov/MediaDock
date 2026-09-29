using Testcontainers.PostgreSql;

namespace MediaDock.IntegrationTests;

internal static class PostgreSqlTestContainerBuilder
{
    public static PostgreSqlBuilder Create(string database)
    {
        return new PostgreSqlBuilder()
            .WithImage("postgres:17-alpine")
            .WithDatabase(database)
            .WithUsername("mediadock")
            .WithPassword("mediadock_test")
            .WithPortBinding(5432, true)
            .WithCreateParameterModifier(parameters =>
            {
                parameters.HostConfig.PortBindings.Values.Single().Single().HostIP = "127.0.0.1";
            });
    }
}