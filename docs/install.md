# Установка CatTunnel на роутер

- [Какой пакет нужен](#какой-пакет-нужен)
- [Одной командой (install.sh)](#одной-командой-installsh)
- [OpenWrt 23.05 / 24.10 (opkg) и 25.x (apk)](#openwrt-2305--2410-opkg-и-25x-apk)
- [Keenetic (Entware)](#keenetic-entware)
- [ASUS Merlin (Entware)](#asus-merlin-entware)
- [Проверка подписи](#проверка-подписи)

## Какой пакет нужен

Архитектуру роутера показывает `uname -m`, а для MIPS дополнительно нужен порядок байт из `opkg print-architecture`. Сборщик поддерживает mips big-endian, однако `install.sh` пока отвергает такую систему; в этом случае автоматический подбор пакета недоступен.

| Файл | Куда |
|---|---|
| `cattunnel_<ver>_openwrt-aarch64.ipk` | OpenWrt, `uname -m` = `aarch64` (например MediaTek Filogic MT7981/MT7986) |
| `cattunnel_<ver>_openwrt-mipsel.ipk` | OpenWrt, `mips` + архитектура `mipsel_*` (MT7621/MT7628) |
| `cattunnel_<ver>_openwrt-armv7.ipk` | OpenWrt, `armv7l` |
| `cattunnel_<ver>_entware-mipsel.ipk` | Keenetic на MT7621, Entware `mipsel-3.4` |
| `cattunnel_<ver>_entware-aarch64.ipk` | Keenetic / ASUS Merlin с Entware `aarch64-3.10` |
| `cattunnel_<ver>_entware-armv7.ipk` | ASUS Merlin с Entware `armv7sf-k3.2` (ядро 2.6 / `armv7sf-k2.6` установщик отвергает) |
| `cattunnel_<ver>_openwrt-x86_64.ipk`, `cattunnel_<ver>_entware-x86_64.ipk` | OpenWrt / Entware на x86_64 (виртуальные машины, мини-ПК) |
| `cattunnel-<ver>-r0_openwrt25-<arch>.apk` | OpenWrt 25.x (apk) |
| `luci-app-cattunnel_<ver>_openwrt-all.ipk` | страницы LuCI для OpenWrt 23.05/24.10 (opkg) |
| `luci-app-cattunnel-<ver>-r0_openwrt25.apk` | страницы LuCI для OpenWrt 25.x (apk) |

Метка `Architecture: all` у `.ipk` и `noarch` у `.apk` относится к пакетному менеджеру: вложенные статические бинарники всё равно собраны для конкретного процессора. `preinst` проверяет архитектуру, платформу и ресурсы; `postinst` дополнительно запускает `trusttunnel_client --version`, поскольку apk 3 может продолжить установку после отказа `preinst`.

Для `.apk` версия преобразуется в формат apk: например, суффикс `-b1` становится `_beta1-r0`, а `-rc1` - `_rc1-r0`. В пакет входят `cattunnel`, `trusttunnel_client`, `age`, `age-keygen`, лицензии и патчи движка.

## Одной командой (install.sh)

```
curl -fsSLO https://github.com/Cattunnel/cattunnel-router/releases/latest/download/install.sh && sh install.sh
```

`build_packages.sh` создаёт `install.sh` с хэшами пакетов, а при наличии ключа подписи добавляет `install.sh.sig` и подпись `SHA256SUMS`. Установщик определяет OpenWrt с opkg, OpenWrt с apk или Entware, проверяет память от 64 МБ, ядро Linux от 3.2, место на диске и в `/tmp`, затем сверяет SHA-256 пакета с данными внутри скрипта.

При обновлении через `install.sh` прежние файлы и база пакетов сохраняются до замены; отказ пакетного менеджера считается ошибкой и вызывает откат. При обновлении работающей службы с включённым kill switch временная блокировка сохраняется до успешной проверки туннеля или истечения срока восстановления и ограничивает транзит выбранных `DEVICES`, а при пустом списке - всего LAN; для резервной копии требуется дополнительное место в `/tmp`.

```
sh install.sh --check          # только проверить
sh install.sh                  # поставить / обновить (+ LuCI, если она есть)
sh install.sh --reinstall      # переставить ту же версию
sh install.sh --file /tmp/<пакет>   # без интернета (scp), хэш всё равно сверяется
sh install.sh --from /tmp/ct   # без интернета: все файлы релиза в папке (пакет + LuCI), хэши сверяются
```

## OpenWrt 23.05 / 24.10 (opkg) и 25.x (apk)

```
opkg update && opkg install curl kmod-tun
opkg install /tmp/cattunnel_<ver>_openwrt-<arch>.ipk
cattunnel import '<ссылка подписки>'   # ключ устройства создаётся автоматически
cattunnel list                       # серверы; * - выбранный
cattunnel use <ключ>                 # выбрать сервер из «cattunnel list»
/etc/init.d/cattunnel start
cattunnel test                       # «ok: интернет через туннель есть»
```
На OpenWrt без внешнего прокси режим `tun` включается командой `cattunnel set MODE tun && cattunnel firewall on && /etc/init.d/cattunnel restart`. Команда `firewall on` создаёт зону fw4 `cattunnel` для `tt0` с маскарадом и пересылкой из LAN в туннель.

На OpenWrt 25.x используются пакеты `…_openwrt25-<arch>.apk` и команда `apk add --allow-untrusted /tmp/<пакет>.apk`. Обновление с резервной копией выполняется через `install.sh`; прямая команда пакетного менеджера не создаёт такую копию.

## Keenetic (Entware)

Для Keenetic нужны компоненты «OPKG» и «Модули ядра подсистемы Netfilter», а также установленный Entware. Он может размещаться во внутренней памяти или на отдельном накопителе; носитель с нужными файлами не подходит для переразметки под Entware.
```
opkg update && opkg install curl
opkg install /tmp/cattunnel_<ver>_entware-mipsel.ipk
cattunnel import '…' 'AGE-SECRET-KEY-1…' && cattunnel list
cattunnel set MODE tun                # весь LAN в туннель; для socks - оставить как есть
/opt/etc/init.d/S99cattunnel start
```
Keenetic пересобирает iptables при изменениях сети, поэтому хук `/opt/etc/ndm/netfilter.d/50-cattunnel.sh` возвращает правила CatTunnel. Помимо маскарада и FORWARD для `tt0`, он восстанавливает метки устройств, доступ к веб-странице и временную блокировку незавершённого обновления.

## ASUS Merlin (Entware)

На ASUS Merlin применяются пакеты Entware для подходящего процессора, обычно `entware-aarch64` или `entware-armv7`. Для возврата правил после пересборки iptables в `/jffs/scripts/nat-start` добавляется `/opt/bin/cattunnel firewall on`, а сам файл должен быть исполняемым; этот хук возвращает правила туннеля, полноценная проверка временной блокировки обновления на Merlin не выполнена.

## Проверка подписи

Для отдельной проверки подписи на ПК применяется `openssl pkeyutl -verify -pubin -inkey cattunnel-release.pub.pem -rawin -in install.sh -sigfile <(base64 -d install.sh.sig)`. При несовместимом бинарнике `postinst` оставляет `WRONG_ARCH`, а `install.sh` повторяет установку подходящего пакета даже при совпадении версии; неудачная первая установка удаляется, обновление восстанавливает сохранённые файлы.
