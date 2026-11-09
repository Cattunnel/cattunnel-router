# shellcheck shell=sh
# Shared by the installer, supervisor and Entware netfilter hook.
# Locks and pending markers survive power loss; no barrier may depend on them forever.
upgrade_lock_live() {
	[ -d "$1/upgrade.lock" ] || return 1
	# An empty directory can be a lock still being initialised by another installer.
	if [ ! -s "$1/upgrade.lock/pid" ] || [ ! -s "$1/upgrade.lock/time" ]; then
		ul_time=$(stat -c %Y "$1/upgrade.lock" 2>/dev/null) || {
			# OpenWrt BusyBox may omit stat. find -mmin has minute resolution.
			[ -n "$(find "$1/upgrade.lock" -maxdepth 0 -mmin -1 -print 2>/dev/null)" ]; return $?
		}
		ul_age=$(( $(date +%s) - ul_time ))
		[ "$ul_age" -ge 0 ] && [ "$ul_age" -lt 5 ]; return $?
	fi
	ul_pid=$(cat "$1/upgrade.lock/pid")
	ul_time=$(cat "$1/upgrade.lock/time")
	if [ -f "$1/upgrade.lock/boot" ]; then
		[ "$(cat "$1/upgrade.lock/boot")" = "$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)" ] || return 1
	fi
	case "$ul_pid" in ''|*[!0-9]*) return 1 ;; esac
	case "$ul_time" in ''|*[!0-9]*) return 1 ;; esac
	[ "${#ul_pid}" -le 10 ] && [ "${#ul_time}" -le 12 ] || return 1
	[ "$ul_pid" -gt 1 ] && kill -0 "$ul_pid" 2>/dev/null || return 1
	# kill -0 also succeeds for an installer awaiting reaping after SIGKILL.
	case "$(awk '$1 == "State:" {print $2}' "/proc/$ul_pid/status" 2>/dev/null)" in Z|X|x) return 1 ;; esac
	ul_age=$(( $(date +%s) - ul_time ))
	[ "$ul_age" -ge 0 ] && [ "$ul_age" -lt 900 ]
}

upgrade_pending_live() {
	[ -f "$1/upgrade.pending" ] || return 1
	[ "$#" -lt 2 ] || [ "$(cat "$1/upgrade.pending" 2>/dev/null)" = "$2" ] || return 1
	if up_time=$(stat -c %Y "$1/upgrade.pending" 2>/dev/null); then
		up_age=$(( $(date +%s) - up_time ))
		if [ "$up_age" -ge 0 ] && [ "$up_age" -lt 900 ]; then return 0; fi
	else
		# Standard OpenWrt images have find -mmin but may have no stat applet.
		[ -z "$(find "$1/upgrade.pending" -mmin -15 -print 2>/dev/null)" ] || return 0
	fi
	# A detached expiry watcher must not expire a following installer's marker.
	[ "$#" -lt 2 ] || [ "$(cat "$1/upgrade.pending" 2>/dev/null)" = "$2" ] || return 1
	rm -f "$1/upgrade.pending"
	upgrade_guard off
	return 1
}

# Explicit installer context also survives apk's sanitised script environment.
upgrade_install_context() {
	upgrade_lock_live "$1" || return 1
	[ "$(cat "$1/upgrade.lock/context" 2>/dev/null)" = install ] || return 1
	# A concurrent user remove must not inherit an unrelated installer's context.
	ui_pid=$$; ui_depth=0
	while [ "$ui_pid" != "$ul_pid" ]; do
		[ "$ui_pid" -gt 1 ] && [ "$ui_depth" -lt 64 ] || return 1
		ui_pid=$(awk '/^PPid:/ {print $2}' "/proc/$ui_pid/status" 2>/dev/null) || return 1
		case "$ui_pid" in ''|*[!0-9]*) return 1 ;; esac
		ui_depth=$((ui_depth + 1))
	done
	ui_keep=$(cat "$1/upgrade.lock/keep-rules" 2>/dev/null) || return 1
	case "$ui_keep" in 0|1) printf '%s\n' "$ui_keep" ;; *) return 1 ;; esac
}

# Old Entware iptables may not support -w. Cache this separately for each family.
guard_xt() {
	gx_bin=$1; shift
	case "$gx_bin" in
		iptables) if [ -z "${GUARD_IP4_WAIT+x}" ]; then GUARD_IP4_WAIT=; iptables -w -L -n >/dev/null 2>&1 && GUARD_IP4_WAIT=-w; fi; gx_wait=$GUARD_IP4_WAIT ;;
		ip6tables) if [ -z "${GUARD_IP6_WAIT+x}" ]; then GUARD_IP6_WAIT=; ip6tables -w -L -n >/dev/null 2>&1 && GUARD_IP6_WAIT=-w; fi; gx_wait=$GUARD_IP6_WAIT ;;
	esac
	"$gx_bin" $gx_wait "$@"
}

guard_family() {
	command -v "$1" >/dev/null 2>&1 || return 1
	[ "$1" != ip6tables ] || { [ -r /proc/net/if_inet6 ] && grep -q . /proc/net/if_inet6; }
}

guard_hosts() {
	for ug_file in /tmp/dhcp.leases /var/lib/misc/dnsmasq.leases; do
		[ ! -f "$ug_file" ] || awk '{print tolower($2), $3, $4, "-"}' "$ug_file"
	done
	ug_ndmc=$(command -v ndmc 2>/dev/null || { [ ! -x /bin/ndmc ] || echo /bin/ndmc; })
	if [ -n "$ug_ndmc" ]; then
		"$ug_ndmc" -c 'show ip hotspot' 2>/dev/null | awk '
		function out() { if (mac != "") print tolower(mac), (ip == "" ? "-" : ip), (hn == "" ? "-" : hn), (nm == "" ? "-" : nm) }
		$1 == "host:" { out(); mac = ip = hn = nm = ""; sub_name = 0; next }
		$1 == "mac:" && mac == "" { mac = $2 }
		$1 == "ip:" && ip == "" { ip = $2 }
		$1 == "hostname:" { hn = $2 }
		$1 == "name:" && nm == "" && mac != "" && sub_name == 0 { $1 = ""; sub(/^ +/, ""); gsub(/ /, "_"); nm = $0 }
		$1 == "interface:" { sub_name = 1 } $1 == "dhcp:" || $1 == "registered:" { sub_name = 0 }
		END { out() }'
	fi
	return 0
}

guard_scope() {  # <settings directory>; "all" or "selected" followed by resolved MACs
	ug_devices=""
	[ ! -f "$1/cattunnel.conf" ] || ug_devices=$(sed -n "s/^DEVICES='\([^']*\)'$/\1/p" "$1/cattunnel.conf")
	if [ -z "$ug_devices" ]; then echo all; return 0; fi
	echo selected
	ug_hosts=$(guard_hosts)
	for ug_device in $ug_devices; do
		case "$ug_device" in
			*:*) printf '%s\n' "$ug_device" | tr 'A-F' 'a-f' ;;
			*) printf '%s\n' "$ug_hosts" | awk -v n="$ug_device" '
				BEGIN { n = tolower(n); pre = (substr(n, length(n)) == "*"); if (pre) n = substr(n, 1, length(n)-1) }
				function hit(x) { x = tolower(x); return x != "-" && (pre ? index(x,n)==1 : x==n) }
				hit($3) || hit($4) { print $1 }' ;;
		esac
	done | grep -E '^([0-9a-f]{2}:){5}[0-9a-f]{2}$' | sort -u
	return 0
}

upgrade_guard() {  # on [settings directory] | off
	case "$1" in
	on)
		if [ -n "${2:-}" ]; then ug_scope=$(guard_scope "$2") || return 1; else ug_scope=all; fi
		ug_selected=0; ug_macs=""
		case "$ug_scope" in selected*) ug_selected=1; ug_macs=$(printf '%s\n' "$ug_scope" | sed '1d') ;; esac
		if [ -f /etc/openwrt_release ] && command -v nft >/dev/null 2>&1; then
			# Replacing the table in one transaction keeps protection continuous when
			# DHCP names or the DEVICES list change while the engine is down.
			{
				if nft list table inet cattunnel_upgrade >/dev/null 2>&1; then echo 'delete table inet cattunnel_upgrade'; fi
				echo 'table inet cattunnel_upgrade {'
				if [ "$ug_selected" = 1 ]; then
					ug_elements=$(printf '%s\n' "$ug_macs" | sed '/^$/d' | tr '\n' ',' | sed 's/,$//')
					if [ -n "$ug_elements" ]; then echo "set macs { type ether_addr; elements = { $ug_elements }; }"
					else echo 'set macs { type ether_addr; }'; fi
				fi
				echo 'chain blocked { counter drop; }'
				# The device marking chains run at priority mangle (-150). Counter
				# collection must precede our drop, and proxy DNAT (-100) must follow it.
				echo 'chain prerouting { type filter hook prerouting priority -110; policy accept;'
				echo 'iifname "lo" accept'
				echo 'meta l4proto ipv6-icmp accept'
				echo 'udp sport { 67, 547 } udp dport { 68, 546 } accept'
				echo 'fib daddr type local accept'
				if [ "$ug_selected" = 1 ]; then
					echo 'meta mark 0x1801 jump blocked'
					echo 'ether saddr @macs jump blocked'
				else echo 'jump blocked'; fi
				echo '}'
				echo 'chain forward { type filter hook forward priority -310; policy accept;'
				if [ "$ug_selected" = 1 ]; then
					echo 'meta mark 0x1801 jump blocked'
					echo 'ether saddr @macs jump blocked'
				else echo 'jump blocked'; fi
				echo '}'; echo '}'
			} | nft -f - || return 1
		else
			for ug_xt in iptables ip6tables; do
				guard_family "$ug_xt" || { [ "$ug_xt" != iptables ] || [ "$1" = off ] || return 1; continue; }
				# Build replacement chains before hooking them in. An existing barrier
				# remains installed until the replacements protect the same traffic.
				ug_slot=A
				guard_xt "$ug_xt" -C FORWARD -j CT_UP_F_A 2>/dev/null && ug_slot=B
				ug_fw=CT_UP_F_$ug_slot; ug_pre=CT_UP_P_$ug_slot
				for ug_chain in "$ug_fw" "$ug_pre"; do
					guard_xt "$ug_xt" -t mangle -N "$ug_chain" 2>/dev/null || true
					guard_xt "$ug_xt" -N "$ug_chain" 2>/dev/null || true
					guard_xt "$ug_xt" -t mangle -F "$ug_chain" || return 1
					guard_xt "$ug_xt" -F "$ug_chain" || return 1
				done
				if guard_xt "$ug_xt" -t mangle -nL CATTUNNEL_DEV >/dev/null 2>&1; then
					guard_xt "$ug_xt" -t mangle -A "$ug_pre" -j CATTUNNEL_DEV || return 1
				fi
				guard_xt "$ug_xt" -t mangle -A "$ug_pre" -m addrtype --dst-type LOCAL -j RETURN || return 1
				if [ "$ug_xt" = ip6tables ]; then
					guard_xt "$ug_xt" -t mangle -A "$ug_pre" -p ipv6-icmp -j RETURN || return 1
				fi
				for ug_table in filter mangle; do
					if [ "$ug_table" = filter ]; then ug_chain=$ug_fw; else ug_chain=$ug_pre; fi
					if [ "$ug_selected" = 1 ]; then
						guard_xt "$ug_xt" -t "$ug_table" -A "$ug_chain" -m mark --mark 0x1801 -j DROP || return 1
						if [ -n "$ug_macs" ] && [ -r /proc/net/ip_tables_matches ]; then
							grep -qw mac /proc/net/ip_tables_matches || { modprobe xt_mac 2>/dev/null || true; }
						fi
						for ug_mac in $ug_macs; do
							guard_xt "$ug_xt" -t "$ug_table" -A "$ug_chain" -m mac --mac-source "$ug_mac" -j DROP || return 1
						done
					else guard_xt "$ug_xt" -t "$ug_table" -A "$ug_chain" -j DROP || return 1; fi
				done
				guard_xt "$ug_xt" -I FORWARD 1 -j "$ug_fw" || return 1
				guard_xt "$ug_xt" -t mangle -I PREROUTING 1 -j "$ug_pre" || return 1
				if [ "$ug_slot" = A ]; then ug_old=B; else ug_old=A; fi
				guard_xt "$ug_xt" -D FORWARD -j CT_UP_F_$ug_old 2>/dev/null || true
				guard_xt "$ug_xt" -t mangle -D PREROUTING -j CT_UP_P_$ug_old 2>/dev/null || true
			done
		fi ;;
	off)
		if [ -f /etc/openwrt_release ] && command -v nft >/dev/null 2>&1; then
			nft delete table inet cattunnel_upgrade 2>/dev/null || true
		else
			for ug_xt in iptables ip6tables; do
				guard_family "$ug_xt" || { [ "$ug_xt" != iptables ] || [ "$1" = off ] || return 1; continue; }
				for ug_slot in A B; do
					guard_xt "$ug_xt" -D FORWARD -j CT_UP_F_$ug_slot 2>/dev/null || true
					guard_xt "$ug_xt" -t mangle -D PREROUTING -j CT_UP_P_$ug_slot 2>/dev/null || true
					for ug_table in filter mangle; do
						for ug_chain in CT_UP_F_$ug_slot CT_UP_P_$ug_slot; do
							guard_xt "$ug_xt" -t "$ug_table" -F "$ug_chain" 2>/dev/null || true
							guard_xt "$ug_xt" -t "$ug_table" -X "$ug_chain" 2>/dev/null || true
						done
					done
				done
			done
		fi ;;
	esac
}

# All-LAN tun mode needs a persistent forwarding barrier as well: a crashed
# engine may remove its routes before the supervisor notices the process exit.
tun_guard() {  # on|off <tun device>, only for tun without DEVICES
	if [ -f /etc/openwrt_release ] && command -v nft >/dev/null 2>&1; then
		if [ "$1" = off ]; then nft delete table inet cattunnel_ks 2>/dev/null || true; return 0; fi
		nft list table inet cattunnel_ks >/dev/null 2>&1 && return 0
		nft -f - <<-RULES
			table inet cattunnel_ks {
			 chain forward {
			  type filter hook forward priority -5; policy accept;
			  oifname "$2" accept
			  iifname "$2" accept
			  ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/3 } accept
			  ip6 daddr { fc00::/7, fe80::/10, ff00::/8 } accept
			  counter drop
			 }
			}
		RULES
	else
		for tg_xt in iptables ip6tables; do
			guard_family "$tg_xt" || { [ "$tg_xt" != iptables ] || [ "$1" = off ] || return 1; continue; }
			if [ "$1" = off ]; then
				guard_xt "$tg_xt" -D FORWARD -j CATTUNNEL_KS 2>/dev/null || true
				guard_xt "$tg_xt" -F CATTUNNEL_KS 2>/dev/null || true
				guard_xt "$tg_xt" -X CATTUNNEL_KS 2>/dev/null || true
				continue
			fi
			guard_xt "$tg_xt" -C FORWARD -j CATTUNNEL_KS 2>/dev/null && continue
			guard_xt "$tg_xt" -N CATTUNNEL_KS 2>/dev/null || true
			guard_xt "$tg_xt" -F CATTUNNEL_KS || return 1
			guard_xt "$tg_xt" -A CATTUNNEL_KS -o "$2" -j RETURN || return 1
			guard_xt "$tg_xt" -A CATTUNNEL_KS -i "$2" -j RETURN || return 1
			if [ "$tg_xt" = iptables ]; then
				tg_nets='0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/3'
			else tg_nets='fc00::/7 fe80::/10 ff00::/8'; fi
			for tg_net in $tg_nets; do guard_xt "$tg_xt" -A CATTUNNEL_KS -d "$tg_net" -j RETURN || return 1; done
			guard_xt "$tg_xt" -A CATTUNNEL_KS -j DROP || return 1
			guard_xt "$tg_xt" -I FORWARD 1 -j CATTUNNEL_KS || return 1
		done
	fi
}
