#!/usr/bin/env bash
set -Eeuo pipefail

iptables_bin=/usr/sbin/iptables
chain=DOCKER-USER
host_ip="${APP_BIND_ADDRESS:-}"
host_port="${APP_PORT:-}"
lan_cidr="${TRUSTED_LAN_CIDR:-}"
action="${1:-apply}"

if (( $# > 1 )) || [[ "$action" != apply && "$action" != remove ]]; then
    printf 'Usage: %s [apply|remove]\n' "$0" >&2
    exit 2
fi

if [[ -z "$host_ip" || -z "$host_port" || -z "$lan_cidr" ]]; then
    printf 'Set APP_BIND_ADDRESS, APP_PORT, and TRUSTED_LAN_CIDR in /etc/default/mediadock-next-firewall.\n' >&2
    exit 1
fi

if [[ ! "$host_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ || "$host_ip" == 0.0.0.0 || "$host_ip" == 127.* ]]; then
    printf 'APP_BIND_ADDRESS must be a specific IPv4 address.\n' >&2
    exit 1
fi

if [[ ! "$host_port" =~ ^[0-9]{1,5}$ ]] || (( 10#$host_port < 1 || 10#$host_port > 65535 )); then
    printf 'APP_PORT must be a valid TCP port.\n' >&2
    exit 1
fi

if [[ ! "$lan_cidr" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]]; then
    printf 'TRUSTED_LAN_CIDR must be an IPv4 subnet in CIDR notation.\n' >&2
    exit 1
fi

if ! "$iptables_bin" -w -S "$chain" >/dev/null 2>&1; then
    if [[ "$action" == remove ]]; then
        exit 0
    fi
    printf 'Required firewall chain is unavailable: %s\n' "$chain" >&2
    exit 1
fi

ensure_rule() {
    local position="$1"
    shift
    if ! "$iptables_bin" -w -C "$chain" "$@" >/dev/null 2>&1; then
        "$iptables_bin" -w -I "$chain" "$position" "$@"
    fi
}

remove_rule() {
    while "$iptables_bin" -w -C "$chain" "$@" >/dev/null 2>&1; do
        "$iptables_bin" -w -D "$chain" "$@"
    done
}

remove_rule -p tcp -m conntrack --ctstate ESTABLISHED --ctorigdst "$host_ip" --ctorigdstport "$host_port" -j RETURN

if [[ "$action" == apply ]]; then
    ensure_rule 1 -p tcp -d "$lan_cidr" -m conntrack --ctstate ESTABLISHED --ctorigdst "$host_ip" --ctorigdstport "$host_port" -j RETURN
    ensure_rule 2 -p tcp -s "$lan_cidr" -m conntrack --ctorigdst "$host_ip" --ctorigdstport "$host_port" -j RETURN
    ensure_rule 3 -p tcp -m conntrack --ctorigdst "$host_ip" --ctorigdstport "$host_port" -j DROP
else
    remove_rule -p tcp -d "$lan_cidr" -m conntrack --ctstate ESTABLISHED --ctorigdst "$host_ip" --ctorigdstport "$host_port" -j RETURN
    remove_rule -p tcp -s "$lan_cidr" -m conntrack --ctorigdst "$host_ip" --ctorigdstport "$host_port" -j RETURN
    remove_rule -p tcp -m conntrack --ctorigdst "$host_ip" --ctorigdstport "$host_port" -j DROP
fi