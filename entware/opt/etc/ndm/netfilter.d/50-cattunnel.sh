#!/bin/sh
# Keenetic пересобирает iptables при каждом изменении сети — возвращаем правила для tun.
running() {  # служба cattunnel запущена (движок работает или ждёт устройства)
	p=$(cat /opt/var/run/cattunnel/run.pid 2>/dev/null) && [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
# ip6tables: только метки DEVICES (IPv6 устройств — тоже в туннель) и отказ их DNS по IPv6
if [ "$type" = "ip6tables" ]; then
	[ "$table" = mangle ] || [ "$table" = filter ] || exit 0
	grep -qx "MODE='tun'" /opt/etc/cattunnel/cattunnel.conf 2>/dev/null || exit 0
	running || exit 0
	grep -q "^DEVICES='[^']" /opt/etc/cattunnel/cattunnel.conf 2>/dev/null && /opt/bin/cattunnel devices on >/dev/null 2>&1
	exit 0
fi
[ "$table" = "nat" ] || [ "$table" = "filter" ] || [ "$table" = "mangle" ] || exit 0
# веб-страница CatTunnel: Keenetic стёр правило INPUT — вернуть (только домашняя сеть)
[ "$table" = filter ] && grep -qx "WEB='on'" /opt/etc/cattunnel/cattunnel.conf 2>/dev/null && /opt/bin/cattunnel web fw >/dev/null 2>&1
# настройки не исполняем (как и сам cattunnel) — только читаем MODE
grep -qx "MODE='tun'" /opt/etc/cattunnel/cattunnel.conf 2>/dev/null || exit 0
# DEVICES: Keenetic стёр и наши метки — вернуть (сторож cattunnel тоже проверяет раз в 30 с).
# И когда движок спит в ожидании устройства: без меток счётчик не растёт и туннель не проснётся.
running && grep -q "^DEVICES='[^']" /opt/etc/cattunnel/cattunnel.conf 2>/dev/null && /opt/bin/cattunnel devices on >/dev/null 2>&1
pgrep -f "^/opt/libexec/cattunnel/trusttunnel_client" >/dev/null 2>&1 || exit 0
/opt/bin/cattunnel firewall on >/dev/null 2>&1
exit 0
