using System.Net;
using System.Net.Sockets;

namespace MediaDock.Infrastructure.Rss;

public interface IRssDnsResolver
{
    Task<IPAddress[]> ResolveAsync(string hostname, CancellationToken cancellationToken);
}

public sealed class SystemRssDnsResolver : IRssDnsResolver
{
    public Task<IPAddress[]> ResolveAsync(string hostname, CancellationToken cancellationToken) =>
        Dns.GetHostAddressesAsync(hostname, cancellationToken);
}

internal static class RssFeedAddressPolicy
{
    private static readonly (IPAddress Network, int PrefixLength)[] BlockedIpv4Networks =
    [
        (IPAddress.Parse("0.0.0.0"), 8),
        (IPAddress.Parse("10.0.0.0"), 8),
        (IPAddress.Parse("100.64.0.0"), 10),
        (IPAddress.Parse("127.0.0.0"), 8),
        (IPAddress.Parse("169.254.0.0"), 16),
        (IPAddress.Parse("172.16.0.0"), 12),
        (IPAddress.Parse("192.0.0.0"), 24),
        (IPAddress.Parse("192.0.2.0"), 24),
        (IPAddress.Parse("192.88.99.0"), 24),
        (IPAddress.Parse("192.168.0.0"), 16),
        (IPAddress.Parse("198.18.0.0"), 15),
        (IPAddress.Parse("198.51.100.0"), 24),
        (IPAddress.Parse("203.0.113.0"), 24),
        (IPAddress.Parse("224.0.0.0"), 4),
        (IPAddress.Parse("240.0.0.0"), 4)
    ];

    private static readonly (IPAddress Network, int PrefixLength)[] BlockedIpv6Networks =
    [
        (IPAddress.Parse("2001::"), 23),
        (IPAddress.Parse("2001:db8::"), 32),
        (IPAddress.Parse("2002::"), 16),
        (IPAddress.Parse("3fff::"), 20)
    ];

    private static readonly IPAddress GlobalIpv6Network = IPAddress.Parse("2000::");

    public static async Task<IPAddress[]> ResolvePublicAddressesAsync(
        IRssDnsResolver resolver,
        string hostname,
        CancellationToken cancellationToken)
    {
        IPAddress[] addresses;
        try
        {
            addresses = await resolver.ResolveAsync(hostname, cancellationToken);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception) when (exception is SocketException or ArgumentException)
        {
            throw new RssFeedDnsException("feed host DNS resolution failed", exception);
        }

        if (addresses.Length == 0 || addresses.Any(address => !IsPublic(address)))
        {
            throw new RssFeedDnsException("feed host resolved to a non-public address");
        }

        return addresses;
    }

    public static async ValueTask<Stream> ConnectAsync(
        SocketsHttpConnectionContext context,
        IRssDnsResolver resolver,
        CancellationToken cancellationToken)
    {
        var addresses = await ResolvePublicAddressesAsync(
            resolver,
            context.DnsEndPoint.Host,
            cancellationToken);
        SocketException? lastSocketException = null;

        foreach (var address in addresses)
        {
            var socket = new Socket(address.AddressFamily, SocketType.Stream, ProtocolType.Tcp);
            try
            {
                await socket.ConnectAsync(
                    new IPEndPoint(address, context.DnsEndPoint.Port),
                    cancellationToken);
                return new NetworkStream(socket, ownsSocket: true);
            }
            catch (SocketException exception)
            {
                socket.Dispose();
                lastSocketException = exception;
            }
            catch
            {
                socket.Dispose();
                throw;
            }
        }

        throw new HttpRequestException("Could not connect to the public feed host.", lastSocketException);
    }

    private static bool IsPublic(IPAddress address)
    {
        if (address.IsIPv4MappedToIPv6)
        {
            address = address.MapToIPv4();
        }

        if (address.AddressFamily == AddressFamily.InterNetwork)
        {
            return !BlockedIpv4Networks.Any(network => IsInNetwork(address, network));
        }

        return address.AddressFamily == AddressFamily.InterNetworkV6
            && IsInNetwork(address, (GlobalIpv6Network, 3))
            && !BlockedIpv6Networks.Any(network => IsInNetwork(address, network));
    }

    private static bool IsInNetwork(
        IPAddress address,
        (IPAddress Network, int PrefixLength) network)
    {
        var addressBytes = address.GetAddressBytes();
        var networkBytes = network.Network.GetAddressBytes();
        if (addressBytes.Length != networkBytes.Length)
        {
            return false;
        }

        var fullBytes = network.PrefixLength / 8;
        for (var index = 0; index < fullBytes; index++)
        {
            if (addressBytes[index] != networkBytes[index])
            {
                return false;
            }
        }

        var remainingBits = network.PrefixLength % 8;
        if (remainingBits == 0)
        {
            return true;
        }

        var mask = (byte)(0xff << (8 - remainingBits));
        return (addressBytes[fullBytes] & mask) == (networkBytes[fullBytes] & mask);
    }
}