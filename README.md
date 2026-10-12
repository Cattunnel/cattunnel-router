# CatTunnel для роутеров

Версия [CatTunnel](https://github.com/Cattunnel/cattunnel) для роутеров: **OpenWrt** (23.05, 24.10, 25.x; страницы в LuCI), **Keenetic** и **ASUS Merlin** (Entware; своя веб-страница). Роутер держит туннель TrustTunnel — тот же движок с доработками, что в приложении (анти-DPI 1–3 и «авто», своя строка, отпечаток TLS, маскировка HTTP/2, отключение QUIC), а управляется командой `cattunnel`, страницами LuCI или веб-страницей.

Подписка — та же ссылка и ключ age, что в приложении; сервер подписок должен отдавать список в формате для роутера (`?format=router`, строка `# cattunnel-router 1` в начале).

> Аккаунт свежий — по соображениям безопасности. Проект ведётся уже около двух месяцев, и автор решил сделать его публичным без привязки к себе. Поэтому история разработки до публикации не перенесена: репозиторий начинается с уже готового кода.

**Установка одной командой** (сам выбирает пакет, проверяет роутер до установки, сверяет подпись и SHA-256):
```
curl -fsSLO https://github.com/Cattunnel/cattunnel-router/releases/latest/download/install.sh && sh install.sh
```

## Два режима

| Режим | Для кого | Как работает |
|---|---|---|
| `socks` (по умолчанию) | OpenWrt с mihomo/nikki (схема nikki + mihomo, [openwrt_vless](https://github.com/PrEvIeS/openwrt_vless)) | SOCKS5 на `127.0.0.1:1080` (TCP и UDP). mihomo сам решает, что пускать в CatTunnel; маршрутизация, zapret и AdGuard Home остаются как были |
| `tun` | «Голый» роутер: OpenWrt без mihomo, Keenetic, ASUS Merlin | устройство `tt0`, движок ставит маршруты, весь LAN идёт в туннель (локальные сети мимо) |

## Пакеты

`./build_packages.sh <версия>` → `build/`:

Какой пакет: на роутере `uname -m` (и для MIPS — порядок байт: `opkg print-architecture`,
`mipsel_*` = little-endian).

| Файл | Куда |
|---|---|
| `cattunnel_<ver>_openwrt-aarch64.ipk` | OpenWrt, `uname -m` = `aarch64` (например MediaTek Filogic MT7981/MT7986 — Cudy TR3000, GL.iNet MT3000) |
| `cattunnel_<ver>_openwrt-mipsel.ipk` | OpenWrt, `mips` + архитектура `mipsel_*` (MT7621/MT7628) |
| `cattunnel_<ver>_openwrt-armv7.ipk` | OpenWrt, `armv7l` |
| `cattunnel_<ver>_entware-mipsel.ipk` | Keenetic на MT7621 (в т.ч. SmartBox Giga KN-1913), Entware `mipsel-3.4` |
| `cattunnel_<ver>_entware-aarch64.ipk` | Keenetic / ASUS Merlin с Entware `aarch64-3.10` |
| `cattunnel_<ver>_entware-armv7.ipk` | ASUS Merlin с Entware `armv7sf-k3.2` (на ядре 2.6 / `armv7sf-k2.6` — не проверено) |
| `cattunnel-<ver>-r0_openwrt25-<arch>.apk` | OpenWrt 25.x (apk) |
| `luci-app-cattunnel_<ver>_openwrt-all.ipk` | страницы LuCI для OpenWrt 23.05/24.10 (opkg) |
| `luci-app-cattunnel-<ver>-r0_openwrt25.apk` | страницы LuCI для OpenWrt 25.x (apk) |

`Architecture: all` — бинарники статические; при установке пакет сам запускает ядро и
откатывается, если процессор не тот. Внутри: `cattunnel`, `trusttunnel_client` (~7–12 МБ),
`age` 1.3.2 (~5 МБ), лицензии и наш патч ядра.

Сборка с нуля: ядро — `engine/build_router.sh` (zig, см. шапку скрипта),
age — `go build filippo.io/age/cmd/age` (CGO_ENABLED=0, GOARCH под роутер, softfloat).

## Установка

### Одной командой (install.sh)
`build_packages.sh` кладёт рядом с пакетами `install.sh` (+ `install.sh.sig`, подпись Ed25519 тем же
ключом, что `latest.json` и Linux-релизы — `cattunnel-release.pub.pem`). Он сам определяет систему
(OpenWrt opkg / OpenWrt 25 apk / Entware) и процессор, проверяет **до** установки место, память,
/tmp, ядро, tun, скачивает пакет с зеркал (`ROUTER_MIRRORS`, по умолчанию
`https://github.com/Cattunnel/cattunnel-router/releases/latest/download`) и сверяет SHA-256 с хэшами, вшитыми в сам `install.sh`;
после установки проверяет, что движок запускается, иначе удаляет пакет.
```
sh install.sh --check          # только проверить
sh install.sh                  # поставить / обновить (+ LuCI, если она есть)
sh install.sh --reinstall      # переставить ту же версию
sh install.sh --file /tmp/<пакет>   # без интернета (scp), хэш всё равно сверяется
sh install.sh --from /tmp/ct   # без интернета: все файлы релиза в папке (пакет + LuCI), хэши сверяются
```
Настройки лежат в `/etc/cattunnel/cattunnel.conf` (Entware: `/opt/etc/cattunnel/cattunnel.conf`) (не в uci): `cattunnel settings` — показать,
`cattunnel set ИМЯ значение` или LuCI — поменять.
Проверить подпись на ПК: `openssl pkeyutl -verify -pubin -inkey cattunnel-release.pub.pem -rawin -in install.sh -sigfile <(base64 -d install.sh.sig)`.

apk 3 (OpenWrt 25) ставит пакет, даже если preinst его отверг; тогда postinst удаляет бинарники,
выключает автозапуск и оставляет `/etc/cattunnel/WRONG_ARCH` — `cattunnel` и LuCI объясняют, что
делать, `install.sh` переставляет нужный пакет сам.

### OpenWrt 23.05 / 24.10 (opkg)
```
opkg update && opkg install curl kmod-tun
opkg install /tmp/cattunnel_<ver>_openwrt-<arch>.ipk
cattunnel import 'https://…/api/ct/<токен>' 'AGE-SECRET-KEY-1…'   # те же ссылка и ключ, что в приложении
cattunnel list                       # серверы; * — выбранный
cattunnel use nl                     # выбрать
/etc/init.d/cattunnel start
cattunnel test                       # «ok: интернет через туннель есть»
```
Режим tun на голом OpenWrt: `cattunnel set MODE tun && cattunnel firewall on && /etc/init.d/cattunnel restart`
(`firewall on` создаёт зону fw4 `cattunnel` на `tt0` с маскарадом и пересылку lan → cattunnel).

OpenWrt 25.x — пакеты `…_openwrt25-<arch>.apk`: `apk add --allow-untrusted /tmp/<пакет>.apk` (или install.sh).

### Только некоторые устройства через туннель (DEVICES, режим tun)
```
cattunnel set MODE tun DEVICES 'aa:bb:cc:dd:ee:ff S22*'   # MAC, имя или начало имени со «*», через пробел
cattunnel firewall on && /etc/init.d/cattunnel restart             # Keenetic: /opt/etc/init.d/S99cattunnel restart
cattunnel devices status
```
Через туннель идут только эти устройства, остальной дом — напрямую. **Туннель по требованию**
(`IDLE_STOP`, по умолчанию 600 с): пока устройства не ходят в интернет, движок не запущен и к серверу
никто не подключается; первый их пакет в интернет (счётчик правила, без локальных сетей/multicast) —
туннель поднимается за ~5–7 с (с kill switch эти секунды они получают отказ, без него — идут напрямую);
IDLE_STOP секунд тишины — гаснет. Телефон дома что-то шлёт постоянно — для него туннель держится, пока
он в сети. `IDLE_STOP 0` — туннель всегда поднят. Как устроено: движок не ставит
общих маршрутов (`included_routes = []`), пакеты устройств помечаются по MAC (OpenWrt — nftables
`inet cattunnel_dev`, Keenetic/Merlin — iptables `CATTUNNEL_DEV`), помеченные идут по таблице 218:
всё в `tt0`, локальные сети — обратно в main (`throw`), туннель пропал — `blackhole` (kill switch только
для них; IPv6 так же). DNS через туннель (`DNS tunnel`) — тоже только для них: их запросы на :53
перенаправляются на семейный DNS из подписки, dnsmasq остальных не трогается. **Телефоны с «частным» (меняющимся) MAC
указывайте по имени** — имя, которое устройство сообщает роутеру, не меняется вместе с MAC. Имена берутся
из аренд DHCP (OpenWrt, ASUS Merlin) и из списка устройств Keenetic (`ndmc show ip hotspot`: и имя
устройства, и имя, данное в Keenetic); новое имя/MAC подхватывается само — сторож сверяет каждые 30 с.
`cattunnel devices status` покажет, что найдено. В LuCI: Настройки → «Только эти
устройства» (галочки по списку устройств в сети). Пусто — весь дом, как раньше.

### Российские сайты — напрямую (RU_DIRECT, режим tun; по умолчанию включено)
Как «Российские сервисы» в приложении: домены `*.ru`/`*.su`/`*.рф`… + встроенный список крупных
сервисов (`/usr/share/cattunnel/ru_services.txt`, тот же, что в приложении) + **сети geoip:ru**
(runetfreedom/geoip, запасной — ipverse; ~26 тыс. IPv4/IPv6), которые CatTunnel скачивает сам раз в
20 часов (`$ETC/ru.cidr`; не скачалось — работает прежний/встроенный). Всё это — исключения движка:
что пришло в туннель к российскому адресу, движок отправляет напрямую с роутера. Без DNS, поэтому
работает и в DEVICES, и для vk.com/Госуслуг/банков (через зарубежный выход они не открываются).
`cattunnel ru status`, `cattunnel ru update`. Выключить: `cattunnel set RU_DIRECT off`.

### Схема с nikki/mihomo
1. Поставить пакет и подписку, как выше; режим `socks` уже по умолчанию.
2. `cattunnel mihomo` — печатает готовые строки для `/etc/nikki/profiles/main.yaml`:
   прокси `CatTunnel` (socks5, udp), группа `VPN` (fallback: CatTunnel → VLESS-REALITY),
   и правила **DIRECT для самого туннеля** (процесс `trusttunnel_client` и адреса наших
   серверов) — их ставить самыми первыми, иначе соединение движка с сервером уйдёт в mihomo
   и завернётся в себя.
3. В селекторы `PROXY`, `YOUTUBE`, `FINAL` добавить `VPN` первым. `service nikki restart`.
4. Проверка: `cattunnel test`; в LuCI → Nikki группа `VPN` показывает CatTunnel живым.
VLESS остаётся запасным: если CatTunnel не отвечает, fallback сам переключится на него.

### Веб-страница на Keenetic / ASUS Merlin
В родной веб-интерфейс Keenetic встроиться нельзя, поэтому у CatTunnel своя страница — это **те же
страницы LuCI** (Состояние, Серверы, Настройки, Диагностика), запущенные через маленькую прослойку
`www/luci-shim.js` вместо LuCI (при сборке они кладутся в пакет Entware; одна кодовая база с OpenWrt).
Команды страниц идут в `cgi-bin/api` (action=exec) с тем же списком разрешённого, что ACL LuCI.
```
cattunnel web password <пароль>      # от 8 символов, пользователь admin
cattunnel web on                     # → http://<домашний адрес роутера>:8090
```
`lighttpd` (+ mod_cgi, mod_auth, mod_authn_file) ставится сам; слушает только домашний адрес (br0),
порт открыт в фаерволе только с br0 (хук netfilter.d возвращает правило после перестроек Keenetic),
вход по паролю; изменения — только POST с заголовком `X-CatTunnel: 1` (чужая страница в браузере его
не пошлёт без CORS), значения проверяет `cattunnel set`. На странице: состояние, запуск/остановка,
устройства сети с галочками «через VPN» (по имени, если есть — переживёт смену MAC), сервер,
kill switch, российские сайты напрямую, минуты тишины. `cattunnel web off` — выключить.
На OpenWrt то же самое — в LuCI (Службы → CatTunnel).

### Keenetic (Entware)
Нужны компоненты «OPKG» и «Модули ядра подсистемы Netfilter», Entware во внутренней памяти
или на отдельной флешке (не на носителе с вашими файлами: Entware его размечает под себя).
```
opkg update && opkg install curl
opkg install /tmp/cattunnel_<ver>_entware-mipsel.ipk
cattunnel import '…' 'AGE-SECRET-KEY-1…' && cattunnel list
cattunnel set MODE tun                # весь LAN в туннель; для socks — оставить как есть
/opt/etc/init.d/S99cattunnel start
```
Keenetic пересобирает iptables сам; хук `/opt/etc/ndm/netfilter.d/50-cattunnel.sh` возвращает
правила (маскарад и FORWARD для `tt0`).

### ASUS Merlin (Entware)
Как Keenetic, пакет `entware-aarch64` или `entware-armv7`. Merlin тоже пересобирает iptables:
добавить в `/jffs/scripts/nat-start` строку `/opt/bin/cattunnel firewall on` (и `chmod +x`).

## Как это устроено
- Подписка: `cattunnel update` качает `<ссылка>?format=router` (бот отдаёт те же серверы, что
  приложению, но готовыми секциями `[endpoint]` для движка), расшифровывает `age` и хранит в
  `/etc/cattunnel/servers.bundle` (600). Не скачалось — пробует зеркала из прошлой подписки.
  При запуске старше 6 часов — обновляется сама.
- `cattunnel run` собирает конфиг движка (`/var/run/cattunnel/client.toml`, 600) из секции
  выбранного сервера и своего режима и запускает движок на переднем плане (procd / start).
- «Авто» анти-DPI: если подписка просит его для сервера, `run` пробует способы 1, 2, 3 по 15 с,
  проверяя интернет через туннель; удачный запоминается для сервера и в следующий раз первый.
- Настройки — `/etc/cattunnel/cattunnel.conf` (`cattunnel set …`), на Entware всё под `/opt`.

## Риски
- Память: ядро 7–12 МБ на диске, ОЗУ при работе — проверить на 128 МБ моделях.
- Режим tun и nikki в режиме tun одновременно не включать — два VPN будут спорить за маршруты.

## Как тестировалось

Проверки — октябрь 2026, на настоящей подписке.

**Стенды**
- OpenWrt 24.10.6 и 25.12.5 x86_64 в QEMU/KVM (256 МБ ОЗУ), OpenWrt 24.10.6 aarch64 в QEMU (cortex-a53), второй виртуальный компьютер в LAN роутера как «устройство».
- OpenWrt со стеком nikki/mihomo + AdGuard Home + zapret.
- Entware x86_64 в контейнере.
- Настоящий **Keenetic** (KN-1913, MT7621 mipsel, KeeneticOS 5.0, Entware во встроенной памяти).
- Бинарники aarch64, armv7, mipsel — также через qemu-user (запуск, SOCKS, расшифровка age).

**Установка и обновление**
- `install.sh --check`; чистая установка (зависимости из репозитория OpenWrt, SHA-256 пакетов); мало места (отказ с советами, ничего не ставится); пакет не той архитектуры (opkg отказывает; apk 3 ставит вопреки preinst — postinst убирает бинарники и выключает автозапуск); Entware без curl (ставится первым).
- Обновление поверх, та же версия, `--reinstall`, удаление (DNS и фаервол возвращаются, интернет напрямую работает), переустановка (настройки подхватываются).
- Проверка обновления с GitHub (`cattunnel upgrade check`): подпись `install.sh` проверена; подделанный `install.sh` отвергается.

**Работа**
- SOCKS5 и tun; DNS через туннель; российские сайты напрямую (по доменам и ~26 тыс. сетей geoip:ru); свой список «напрямую».
- Kill switch: сервер пропал — напрямую ничего не уходит. Смена сервера при отказе (~30 с).
- «Только эти устройства» по MAC и по имени (в т.ч. телефоны с меняющимся MAC), IPv6 этих устройств через туннель, их DNS по IPv6 не уходит мимо туннеля.
- Туннель по требованию: без устройств движок не работает, поднимается за 5–7 с, когда устройство выходит в интернет. Метки устройств возвращаются сами после пересборки iptables на Keenetic.
- Встраивание в nikki/mihomo: CatTunnel первым в группах, запрос из LAN через mihomo проходит; mihomo в режиме fake-ip — имена серверов разрешаются в обход.
- Строгая проверка сертификатов: настоящий Russian Trusted Root CA убирается из набора, подключение работает.
- Веб-страница на Keenetic: без пароля / неверный — 401, POST без заголовка — 403; выключить страницу с самой страницы нельзя; страницы LuCI через прослойку проверены в Chromium (светлая и тёмная тема, 1280 и 390 px).

**Краш-тесты**
- Свежая установка без файла проверки обновлений, мусорный и пустой файл — сторож работает, не перезапускается (OpenWrt 25.12, 10 мин на настоящем сервере); `kill -9` сторожа — procd поднимает новый, лишний движок гасится один раз.
- Подписка-мусор, пустая, обрезанная; `kill -9` движка 5 раз подряд; 10 перезапусков подряд — всегда один движок и один сторож, без «сирот».
- Файл настроек с мусором и `$(команда)` — не исполняется; значения с кавычками, `;`, `$()`, `../` — отклоняются.
- WAN пропал на 150 с — утечек нет; 3×300 параллельных запросов — память движка 8 → 12 МБ и не растёт; 20 МБ свободной памяти — работает; перезагрузка с WAN и без — туннель поднимается сам.

**Не проверено вживую**
- ASUS Merlin (пакет и команды те же, что для Entware на Keenetic, но на настоящем роутере не запускались).
- Настоящие роутеры aarch64 и armv7 (только VM и qemu-user).
- Переключение nikki на запасной VLESS при отказе CatTunnel.
- «SHA-256 не совпал» и «зеркало не отвечает» в `install.sh` — проверено по коду.

---

При разработке использовался ИИ-ассистент Claude.

