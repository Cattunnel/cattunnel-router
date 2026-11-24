English: [install.en.md](install.en.md)

# Установка CatTunnel на роутер

- [Какой пакет нужен](#какой-пакет-нужен)
- [Одной командой (install.sh)](#одной-командой-installsh)
- [OpenWrt 23.05 / 24.10 (opkg) и 25.x (apk)](#openwrt-2305--2410-opkg-и-25x-apk)
- [Keenetic (Entware)](#keenetic-entware)
- [ASUS Merlin (Entware)](#asus-merlin-entware)
- [Проверка подписи](#проверка-подписи)

## Какой пакет нужен

Процессор роутера показывает `uname -m`, а для MIPS порядок байт определяется по `opkg print-architecture`. Сборщик умеет делать пакет для mips big-endian, но `install.sh` такую систему пока отвергает.

| Файл | Куда |
|---|---|
| `cattunnel_<ver>_openwrt-aarch64.ipk` | OpenWrt, `uname -m` равен `aarch64` |
| `cattunnel_<ver>_openwrt-mipsel.ipk` | OpenWrt, MIPS little-endian (архитектура пакетов `mipsel_*`) |
| `cattunnel_<ver>_openwrt-armv7.ipk` | OpenWrt, `armv7l` |
| `cattunnel_<ver>_openwrt-x86_64.ipk`, `cattunnel_<ver>_entware-x86_64.ipk` | OpenWrt или Entware на x86_64 |
| `cattunnel_<ver>_entware-<arch>.ipk` | Keenetic и ASUS Merlin с Entware; `<arch>` равен `aarch64`, `armv7` или `mipsel` |
| `cattunnel-<ver>-r0_openwrt25-<arch>.apk` | OpenWrt 25.x (apk) |
| `luci-app-cattunnel_<ver>_openwrt-all.ipk` | страницы LuCI для OpenWrt 23.05 и 24.10 |
| `luci-app-cattunnel-<ver>-r0_openwrt25.apk` | страницы LuCI для OpenWrt 25.x |

Метка `Architecture: all` у `.ipk` и `noarch` у `.apk` относится к пакетному менеджеру: бинарники внутри статические и собраны под конкретный процессор. Перед распаковкой `preinst` проверяет процессор, платформу, место, память и ядро. После установки `postinst` запускает `trusttunnel_client --version`, потому что apk 3 может продолжить установку после отказа `preinst`.

Для `.apk` версия переводится в формат apk: суффикс `-b1` становится `_beta1-r0`, а `-rc1` становится `_rc1-r0`. В пакет входят `cattunnel`, `trusttunnel_client`, `age`, `age-keygen`, лицензии и патчи движка.

## Одной командой (install.sh)

```
curl -fsSLO https://github.com/Cattunnel/cattunnel-router/releases/latest/download/install.sh && sh install.sh
```

Установщик определяет систему (OpenWrt с opkg, OpenWrt с apk или Entware) и процессор, затем проверяет ядро Linux от 3.2, память от 64 МБ, место на диске и в `/tmp`. Дальше он скачивает пакет и сверяет его SHA-256 с хэшем, вшитым в сам `install.sh`.

```text
install.sh --> система и процессор --> проверки (ядро, память, место, /tmp, tun)
                                              |
                  не прошли: ничего не ставится, причина выведена
                                              v
           скачать пакет с зеркала --> сверить SHA-256 --> сохранить старый пакет
                                              v
              установить --> движок запускается? --нет--> откат
                                              |да
                                              v
                             установить страницы LuCI (OpenWrt)
```

Рисунок 1. Что делает `install.sh`.

При обновлении прежние файлы и база пакетов сохраняются до замены, отказ пакетного менеджера считается ошибкой и вызывает откат. Если работающая служба обновляется с включённым kill switch, временная блокировка держится, пока туннель не пройдёт проверку или не истечёт срок восстановления. Она ограничивает транзит выбранных `DEVICES`, а при пустом списке всего LAN. Для резервной копии нужно дополнительное место в `/tmp`.

```
sh install.sh --check          # только проверить
sh install.sh                  # поставить или обновить (плюс LuCI, если она есть)
sh install.sh --reinstall      # переставить ту же версию
sh install.sh --no-luci        # без страниц LuCI
sh install.sh --file /tmp/<пакет>   # без интернета (scp), хэш всё равно сверяется
sh install.sh --from /tmp/ct   # без интернета: все файлы релиза в папке, хэши сверяются
```

## OpenWrt 23.05 / 24.10 (opkg) и 25.x (apk)

```
opkg update && opkg install curl kmod-tun
opkg install /tmp/cattunnel_<ver>_openwrt-<arch>.ipk
cattunnel import '<ссылка подписки>'   # ключ устройства создаётся автоматически
cattunnel list                       # серверы; * это выбранный
cattunnel use <ключ>                 # выбрать сервер из «cattunnel list»
/etc/init.d/cattunnel start
cattunnel test                       # «ok: интернет через туннель есть»
```

На OpenWrt без внешнего прокси режим `tun` включается так: `cattunnel set MODE tun && cattunnel firewall on && /etc/init.d/cattunnel restart`. Команда `firewall on` создаёт зону fw4 `cattunnel` для `tt0` с маскарадом и пересылкой из LAN в туннель.

На OpenWrt 25.x ставятся пакеты `…_openwrt25-<arch>.apk` командой `apk add --allow-untrusted /tmp/<пакет>.apk`. Обновление с резервной копией выполняет `install.sh`, прямая команда пакетного менеджера такую копию не делает.

## Keenetic (Entware)

Нужны компонент «OPKG» и установленный Entware. Если Entware не найден (нет `/opt/bin/opkg`), установщик остановится и подскажет, что сделать.

```
opkg update && opkg install curl
opkg install /tmp/cattunnel_<ver>_entware-<arch>.ipk
cattunnel import '…' 'AGE-SECRET-KEY-1…' && cattunnel list
cattunnel set MODE tun                # весь LAN в туннель; для socks оставьте как есть
/opt/etc/init.d/S99cattunnel start
```

Keenetic пересобирает iptables при изменениях сети, поэтому хук `/opt/etc/ndm/netfilter.d/50-cattunnel.sh` возвращает правила CatTunnel: маскарад и FORWARD для `tt0`, метки устройств, доступ к веб-странице и временную блокировку незавершённого обновления.

## ASUS Merlin (Entware)

На ASUS Merlin ставится пакет Entware для подходящего процессора. Чтобы правила возвращались после пересборки iptables, добавьте в `/jffs/scripts/nat-start` строку `/opt/bin/cattunnel firewall on` и сделайте файл исполняемым. Этот хук возвращает правила туннеля. Временная блокировка при обновлении на Merlin отдельно не проверялась.

## Проверка подписи

Подпись `install.sh` можно проверить на ПК: `openssl pkeyutl -verify -pubin -inkey cattunnel-release.pub.pem -rawin -in install.sh -sigfile <(base64 -d install.sh.sig)`. Открытый ключ лежит в `keys/cattunnel-release.pub.pem` и входит в каждый пакет.

Если бинарник не подходит процессору, `postinst` оставляет метку `WRONG_ARCH`, а `install.sh` ставит подходящий пакет даже при совпадении версии. Неудачная первая установка удаляется, при обновлении восстанавливаются сохранённые файлы.
