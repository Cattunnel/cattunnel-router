#!/usr/bin/env bash
# Пакеты CatTunnel для роутеров из готовых бинарников (engine/build_router.sh
# + статический age): .ipk для OpenWrt (opkg, 23.05/24.10) и для Entware (Keenetic, ASUS Merlin).
#
#   ./build_packages.sh <версия> [arch...]     arch: aarch64 armv7 mipsel mips x86_64
#   -> build/cattunnel_<версия>_openwrt-<arch>.ipk, cattunnel_<версия>_entware-<arch>.ipk, SHA256SUMS
#
# Architecture: all — бинарники статические, подходят к любому варианту процессора семейства;
# postinst сам проверяет, что ядро запускается, и иначе откатывает установку.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
VER=${1:?usage: build_packages.sh <версия> [arch...]}
shift
ARCHES=${*:-aarch64 armv7 mipsel}
BIN=${ROUTER_BIN:-$HOME/tt-build/router-bin}
OUT=$ROOT/build
AGE_LICENSE=${AGE_LICENSE:-$(ls -d "$HOME"/tt-build/gopath/pkg/mod/filippo.io/age@*/ 2>/dev/null | tail -1)LICENSE}
mkdir -p "$OUT"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
# OpenWrt 25.x — apk (apk-tools 3, ADB). Нужен apk с mkpkg (OpenWrt кладёт урезанный); собран из
# apk-tools v3.0.5: APK=~/tt-build/apk-tools/apk. Нет его — .apk не делаем, .ipk как раньше.
APK=${APK:-$HOME/tt-build/apk-tools/apk}
apkver() { printf '%s' "$1" | sed -E 's/-b([0-9]+)$/_beta\1/; s/-rc([0-9]+)$/_rc\1/'; echo "-r0"; }
mkapk() {  # <stage dir> <name> <depends> <description> <out.apk>
	[ -x "$APK" ] || return 0
	local d=$1 sc=()
	[ -f "$d/control/preinst" ] && sc+=(--script "pre-install:$d/control/preinst" --script "pre-upgrade:$d/control/preinst")
	[ -f "$d/control/postinst" ] && sc+=(--script "post-install:$d/control/postinst" --script "post-upgrade:$d/control/postinst")
	[ -f "$d/control/prerm" ] && sc+=(--script "pre-deinstall:$d/control/prerm")
	# fakeroot: владелец файлов в пакете — root (иначе на роутере это несуществующий пользователь)
	LD_LIBRARY_PATH=$(dirname "$APK") fakeroot "$APK" mkpkg --files "$d/data" \
		--info "name:$2" --info "version:$(apkver "$VER")" --info "arch:noarch" \
		--info "description:$4" --info "license:Apache-2.0" --info "depends:$3" \
		"${sc[@]}" --output "$5"
	echo "$5 $(stat -c %s "$5")"
}

help_into() {  # <папка>: «Справка» — наш текст про роутер + «Как устроено подключение» из приложения (движок общий)
	install -Dm644 "$ROOT/help/ROUTER.ru.md" "$1/ROUTER.ru.md"
	install -Dm644 "$ROOT/shared/CONNECTION.ru.md" "$1/CONNECTION.ru.md"
}

ipk() {  # <dir with control/ and data/> <out.ipk>
	local d=$1
	printf '2.0\n' > "$d/debian-binary"
	tar --format=gnu --owner=0 --group=0 --numeric-owner -C "$d/control" -czf "$d/control.tar.gz" .
	tar --format=gnu --owner=0 --group=0 --numeric-owner -C "$d/data" -czf "$d/data.tar.gz" .
	tar --format=gnu --owner=0 --group=0 --numeric-owner -C "$d" -czf "$2" ./debian-binary ./data.tar.gz ./control.tar.gz
}

for A in $ARCHES; do
	[ -x "$BIN/trusttunnel_client-$A" ] || { echo "нет $BIN/trusttunnel_client-$A" >&2; exit 1; }
	[ -x "$BIN/age-$A" ] || { echo "нет $BIN/age-$A" >&2; exit 1; }
	for FLAVOR in openwrt entware; do
		d=$work/$FLAVOR-$A; rm -rf "$d"; mkdir -p "$d/control" "$d/data"
		if [ $FLAVOR = openwrt ]; then P=""; LIBX=/usr/libexec/cattunnel; BINDIR=/usr/bin; ETC=/etc/cattunnel
			install -Dm755 "$ROOT/openwrt/cattunnel/files/etc/init.d/cattunnel" "$d/data/etc/init.d/cattunnel"
			# своя веб-страница (cattunnel web on) — и на OpenWrt, рядом с LuCI: те же страницы через прослойку
			mkdir -p "$d/data/usr/share/cattunnel"
			cp -a "$ROOT/entware/opt/share/cattunnel/www" "$d/data/usr/share/cattunnel/"
			cp -a "$ROOT/openwrt/luci-app-cattunnel/htdocs/luci-static/resources/." "$d/data/usr/share/cattunnel/www/luci/"
			help_into "$d/data/usr/share/cattunnel/www/luci/cattunnel/help"
			DEPENDS="libc, curl, kmod-tun"
		else P=/opt; LIBX=/opt/libexec/cattunnel; BINDIR=/opt/bin; ETC=/opt/etc/cattunnel
			cp -a "$ROOT/entware/opt/." "$d/data/opt/"
			# веб-страница Keenetic/Merlin запускает ТЕ ЖЕ страницы LuCI через прослойку (www/luci-shim.js)
			mkdir -p "$d/data/opt/share/cattunnel/www/luci"
			cp -a "$ROOT/openwrt/luci-app-cattunnel/htdocs/luci-static/resources/." "$d/data/opt/share/cattunnel/www/luci/"
			help_into "$d/data/opt/share/cattunnel/www/luci/cattunnel/help"
			DEPENDS="curl"
		fi
		install -Dm755 "$ROOT/common/cattunnel" "$d/data$BINDIR/cattunnel"
		install -Dm755 "$BIN/trusttunnel_client-$A" "$d/data$LIBX/trusttunnel_client"
		install -Dm755 "$BIN/age-$A" "$d/data$LIBX/age"
		install -Dm644 "$HOME/tt-build/TTC-clean/LICENSE" "$d/data$P/usr/share/doc/cattunnel/LICENSE.TrustTunnelClient"
		install -Dm644 "$AGE_LICENSE" "$d/data$P/usr/share/doc/cattunnel/LICENSE.age"
		install -Dm644 "$ROOT/engine/0001-anti-dpi-desync.patch" "$d/data$P/usr/share/doc/cattunnel/0001-anti-dpi-desync.patch"
		# встроенные российские домены/сети (как в приложении) — RU_DIRECT работает и без скачанного списка
		install -Dm644 "$ROOT/shared/ru_services.txt" "$d/data$P/usr/share/cattunnel/ru_services.txt"
		# самообновление: своя версия, зеркала и ключ, которым подписан install.sh (cattunnel upgrade)
		echo "$VER" > "$d/data$P/usr/share/cattunnel/VERSION"
		echo "${ROUTER_MIRRORS:-https://github.com/Cattunnel/cattunnel-router/releases/latest/download}" > "$d/data$P/usr/share/cattunnel/MIRRORS"
		install -Dm644 "$ROOT/keys/cattunnel-release.pub.pem" "$d/data$P/usr/share/cattunnel/release.pub.pem"
		size=$(du -sk "$d/data" | cut -f1)
		cat > "$d/control/control" <<-EOF
			Package: cattunnel
			Version: $VER
			Depends: $DEPENDS
			Section: net
			Architecture: all
			Installed-Size: $((size * 1024))
			Maintainer: CatTunnel
			Description: CatTunnel for routers ($FLAVOR, $A) - TrustTunnel client (own build with anti-DPI)
			 as a SOCKS5 outbound for mihomo or a tun VPN for the whole LAN. Command: cattunnel.
		EOF
		# preinst: проверка ДО распаковки — не тот процессор, мало места/памяти, старое ядро,
		# не та платформа — opkg ничего не ставит и объясняет почему.
		need_kb=$(( size + 2048 ))
		echo "$FLAVOR $A cattunnel_${VER}_$FLAVOR-$A.ipk $need_kb" >> "$work/pkgs"
		[ $FLAVOR = openwrt ] && [ -x "$APK" ] && echo "openwrt25 $A cattunnel-$(apkver "$VER")_openwrt25-$A.apk $need_kb" >> "$work/pkgs"
		cat > "$d/control/preinst" <<-EOF
			#!/bin/sh
			[ -n "\${IPKG_INSTROOT:-}" ] && exit 0
			# старая версия держала «автозапуск выключен» в самом S99cattunnel, а пакет его перезапишет
			if grep -q '^ENABLED=no' /opt/etc/init.d/S99cattunnel 2>/dev/null; then mkdir -p /opt/etc/cattunnel && touch /opt/etc/cattunnel/autostart.off; fi
			fail() { echo "cattunnel: установка отменена — \$*" >&2; exit 1; }
			warn() { echo "cattunnel: внимание — \$*" >&2; }
			want=$A; flavor=$FLAVOR
			m=\$(uname -m)
			le=\$(printf '\\001\\000' | hexdump -e '1/2 "%d"' 2>/dev/null)
			[ -n "\$le" ] || le=\$( [ -n "\$(opkg print-architecture 2>/dev/null | grep -E 'mipsel|mips64el')" ] && echo 1 || echo 256)
			case "\$want" in
				aarch64) case "\$m" in aarch64|arm64) ;; *) fail "этот пакет для ARM64 (aarch64), а процессор роутера: \$m" ;; esac ;;
				armv7)   case "\$m" in armv7*|armv8l) ;; *) fail "этот пакет для ARMv7, а процессор роутера: \$m" ;; esac ;;
				x86_64)  [ "\$m" = x86_64 ] || fail "этот пакет для x86_64, а процессор роутера: \$m" ;;
				mipsel)  case "\$m" in mips*) [ "\$le" = 1 ] || fail "этот пакет для MIPS little-endian (mipsel), а у роутера big-endian — нужен пакет mips" ;; *) fail "этот пакет для MIPS (mipsel), а процессор роутера: \$m" ;; esac ;;
				mips)    case "\$m" in mips*) [ "\$le" != 1 ] || fail "этот пакет для MIPS big-endian, а у роутера little-endian — нужен пакет mipsel" ;; *) fail "этот пакет для MIPS, а процессор роутера: \$m" ;; esac ;;
			esac
			if [ "\$flavor" = openwrt ]; then
				[ -f /etc/openwrt_release ] || fail "это пакет для OpenWrt, а здесь не OpenWrt (для Keenetic/Merlin — пакет entware)"
				target=/
			else
				[ ! -f /etc/openwrt_release ] || fail "это пакет для Entware (Keenetic/Merlin), а здесь OpenWrt — нужен пакет openwrt"
				[ -d /opt/etc ] || fail "не найден Entware (/opt/etc) — сначала установите Entware"
				target=/opt
			fi
			free=\$(df -k "\$target" 2>/dev/null | awk 'NR==2 {print \$4}')
			[ -z "\$free" ] || [ "\$free" -ge $need_kb ] || fail "мало места в \$target: свободно \$((free / 1024)) МБ, нужно \$(($need_kb / 1024)) МБ (на OpenWrt — extroot на флешку)"
			mem=\$(awk '/^MemTotal:/ {print int(\$2 / 1024)}' /proc/meminfo)
			[ "\${mem:-0}" -ge 60 ] || fail "мало памяти: \${mem} МБ, нужно от 64 МБ"
			kv=\$(uname -r | awk -F. '{print \$1 * 100 + \$2}')
			[ "\${kv:-0}" -ge 302 ] || fail "ядро \$(uname -r) слишком старое, нужно 3.2 или новее"
			[ -c /dev/net/tun ] || [ -n "\$(opkg list-installed kmod-tun 2>/dev/null)" ] || warn "нет /dev/net/tun — режим tun работать не будет (SOCKS для mihomo — будет); OpenWrt: opkg install kmod-tun"
			echo "cattunnel: проверка пройдена — \$m, \$((free / 1024)) МБ свободно, \${mem} МБ памяти, ядро \$(uname -r)"
			exit 0
		EOF
		cat > "$d/control/postinst" <<-EOF
			#!/bin/sh
			# Не тот процессор. opkg до сюда не доходит (preinst), а apk 3 ошибку preinst игнорирует —
			# поэтому здесь: убрать бинарники, выключить автозапуск, оставить метку и громко сказать.
			if ! $LIBX/trusttunnel_client --version >/dev/null 2>&1; then
			  msg="пакет не для этого роутера: процессор \$(uname -m), а пакет собран для $A. Удалите его (OpenWrt 25: apk del cattunnel, иначе opkg remove cattunnel) и поставьте нужный — проще всего через install.sh, он выбирает пакет сам"
			  rm -f $LIBX/trusttunnel_client $LIBX/age
			  mkdir -p $ETC && echo "\$msg" > $ETC/WRONG_ARCH
			  [ ! -x /etc/init.d/cattunnel ] || /etc/init.d/cattunnel disable >/dev/null 2>&1 || true
			  for fd in 1 2; do printf '\n!!! cattunnel: %s !!!\n\n' "\$msg" >&\$fd; done
			  exit 1
			fi
			rm -f $ETC/WRONG_ARCH
			mkdir -p $ETC && chmod 700 $ETC
			[ -f $ETC/cattunnel.conf ] || { echo "# Настройки CatTunnel: cattunnel set / import / use (или LuCI)" > $ETC/cattunnel.conf; chmod 600 $ETC/cattunnel.conf; }
			rm -f $ETC/cattunnel.conf-opkg
			# Соседи по роутеру: при первой установке — сразу встроиться (режим/DNS/порт под их схему),
			# при обновлении — только показать, чужие и свои настройки не трогать.
			echo "--- соседи по роутеру (cattunnel doctor) ---"
			if [ -s $ETC/servers.bundle ]; then $BINDIR/cattunnel doctor 2>/dev/null; else $BINDIR/cattunnel doctor --apply 2>/dev/null; fi
			echo "CatTunnel установлен. Дальше: cattunnel import <ссылка подписки> <age-ключ>; cattunnel list; cattunnel test"
			[ -n "\${IPKG_INSTROOT:-}" ] || [ ! -s $ETC/servers.bundle ] || [ ! -x /opt/etc/init.d/S99cattunnel ] || [ -f $ETC/autostart.off ] || /opt/etc/init.d/S99cattunnel restart
			exit 0
		EOF
		cat > "$d/control/prerm" <<-EOF
			#!/bin/sh
			$BINDIR/cattunnel stop >/dev/null 2>&1 || true
			[ "\${1:-}" = upgrade ] || [ -f /etc/openwrt_release ] || $BINDIR/cattunnel cleanup >/dev/null 2>&1 || true
			exit 0
		EOF
		if [ $FLAVOR = openwrt ]; then
			cat >> "$d/control/postinst" <<-'EOF'
			EOF
			# включить автозапуск; после обновления — запустить снова (prerm его остановил), если подписка есть
			sed -i 's|^exit 0$|if [ -z "${IPKG_INSTROOT:-}" ]; then /etc/init.d/cattunnel enable; [ -s /etc/cattunnel/servers.bundle ] \&\& /etc/init.d/cattunnel restart; fi\nexit 0|' "$d/control/postinst"
			# удаление (не обновление): вернуть DNS и фаервол, иначе роутер останется без интернета
			sed -i 's|^exit 0$|/etc/init.d/cattunnel stop >/dev/null 2>\&1\nif [ "${1:-}" != upgrade ]; then /etc/init.d/cattunnel disable >/dev/null 2>\&1; /usr/bin/cattunnel cleanup >/dev/null 2>\&1; fi\nexit 0|' "$d/control/prerm"
		fi
		chmod 755 "$d/control/preinst" "$d/control/postinst" "$d/control/prerm"
		ipk "$d" "$OUT/cattunnel_${VER}_$FLAVOR-$A.ipk"
		echo "$OUT/cattunnel_${VER}_$FLAVOR-$A.ipk $(stat -c %s "$OUT/cattunnel_${VER}_$FLAVOR-$A.ipk")"
		[ $FLAVOR = openwrt ] && mkapk "$d" cattunnel "libc curl kmod-tun" \
			"CatTunnel for routers ($A) - TrustTunnel client with anti-DPI; SOCKS5 for mihomo or tun for the LAN" \
			"$OUT/cattunnel-$(apkver "$VER")_openwrt25-$A.apk"
	done
done
# LuCI (OpenWrt 23.05/24.10/25.12 — JS-страницы одинаковые): Службы → CatTunnel
d=$work/luci; mkdir -p "$d/control" "$d/data/www"
cp -a "$ROOT/openwrt/luci-app-cattunnel/htdocs/." "$d/data/www/"
help_into "$d/data/www/luci-static/resources/cattunnel/help"
cp -a "$ROOT/openwrt/luci-app-cattunnel/root/." "$d/data/"
cat > "$d/control/control" <<-EOF
	Package: luci-app-cattunnel
	Version: $VER
	Depends: cattunnel, luci-base, rpcd
	Section: luci
	Architecture: all
	Installed-Size: $(( $(du -sk "$d/data" | cut -f1) * 1024 ))
	Maintainer: CatTunnel
	Description: LuCI pages for CatTunnel: status, servers from the subscription, settings, diagnostics.
EOF
cat > "$d/control/postinst" <<-'EOF'
	#!/bin/sh
	[ -n "${IPKG_INSTROOT:-}" ] && exit 0
	rm -f /tmp/luci-indexcache* /tmp/luci-modulecache/* 2>/dev/null
	/etc/init.d/rpcd reload 2>/dev/null
	exit 0
EOF
chmod 755 "$d/control/postinst"
ipk "$d" "$OUT/luci-app-cattunnel_${VER}_openwrt-all.ipk"
mkapk "$d" luci-app-cattunnel "cattunnel luci-base rpcd" "LuCI pages for CatTunnel" "$OUT/luci-app-cattunnel-$(apkver "$VER")_openwrt25.apk"
echo "$OUT/luci-app-cattunnel_${VER}_openwrt-all.ipk $(stat -c %s "$OUT/luci-app-cattunnel_${VER}_openwrt-all.ipk")"

luci_kb=$(( $(du -sk "$d/data" | cut -f1) + 64 ))
echo "luci-openwrt all luci-app-cattunnel_${VER}_openwrt-all.ipk $luci_kb" >> "$work/pkgs"
[ -x "$APK" ] && echo "luci-openwrt25 all luci-app-cattunnel-$(apkver "$VER")_openwrt25.apk $luci_kb" >> "$work/pkgs"

# install.sh: сам выбирает пакет под роутер, проверяет до установки, сверяет SHA-256 с вшитыми
# сюда хэшами. Зеркала — папки, куда выкладываются эти файлы (через пробел, по порядку).
MIRRORS=${ROUTER_MIRRORS:-https://github.com/Cattunnel/cattunnel-router/releases/latest/download}
while read -r kind arch file kb; do
	printf '%s %s %s %s %s\n' "$kind" "$arch" "$file" "$(sha256sum "$OUT/$file" | cut -d' ' -f1)" "$kb"
done < "$work/pkgs" > "$work/pkgs.sha"
sed -e "s|@VER@|$VER|" -e "s|@MIRRORS@|$MIRRORS|" -e "/^@PKGS@\$/{r $work/pkgs.sha" -e "d}" \
	"$ROOT/install.sh.in" > "$OUT/install.sh"
chmod 755 "$OUT/install.sh"
sh -n "$OUT/install.sh"
echo "$OUT/install.sh $(stat -c %s "$OUT/install.sh")"

(cd "$OUT" && sha256sum install.sh cattunnel_*.ipk luci-app-cattunnel_*.ipk $(ls *.apk 2>/dev/null) > SHA256SUMS)
# Подпись Ed25519 тем же ключом, что latest.json и Linux-релизы (cattunnel-release.pub.pem)
KEYF=${UPDATE_SIGNING_KEY:-$ROOT/keys/update-signing.pem}
if [ -e "$KEYF" ]; then
	for f in install.sh SHA256SUMS; do
		UPDATE_SIGNING_KEY=$KEYF "$ROOT/keys/sign_latest_json.sh" sign "$OUT/$f" >/dev/null
		openssl pkeyutl -verify -pubin -inkey "$ROOT/keys/cattunnel-release.pub.pem" -rawin \
			-in "$OUT/$f" -sigfile <(base64 -d "$OUT/$f.sig") >/dev/null || { echo "$f.sig не сходится с ключом" >&2; exit 1; }
	done
	cp "$ROOT/keys/cattunnel-release.pub.pem" "$OUT/"
else
	echo "ВНИМАНИЕ: нет ключа подписи ($KEYF) — install.sh и SHA256SUMS без .sig" >&2
fi
