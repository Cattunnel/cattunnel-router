# Сборка пакетов

Скрипт `./build_packages.sh <версия>` сохраняет пакеты в `build/`, по умолчанию собирая aarch64, armv7 и mipsel. Для x86_64 или mips архитектуру нужно передать аргументом; `.apk` создаются только при наличии исполняемого `APK` с командой `mkpkg`.

Версия age не закреплена в `build_packages.sh`: сборщик использует готовые бинарники из `ROUTER_BIN`, поэтому её нужно сверять с исходниками этих бинарников.

## Ядро

Скрипт `engine/build_router.sh` закрепляет ревизию `b59debf4` TrustTunnelClient: то же ядро, что в Android 1.5.9.5 (ротация IP без обрывов, пул соединений с паузами между рукопожатиями, исправление Ed25519 для MIPS). На aarch64, armv7 и x86_64 выбран `openssl/boring-2026-05-08@adguard/oss` с `SSL_set_custom_client_random` и ML-DSA; на mips/mipsel остаётся `openssl/4.0.2@adguard/oss`, поэтому TLS-ключ авторизации `client_random_auth_key` (тег 0x0F) на mips/mipsel не работает. Фактическая готовность бинарников и их размеры фиксируются в отчёте сборки.

Патчи в `engine/` (анти-DPI, монитор сети для policy routing, исправления сборки NativeLibsCommon и DnsLibs) относятся к более ранним версиям ядра. Изменения ревизий `82963908` и `b59debf4` сверх них (пул соединений, формирователь набивки, браузерные заголовки `CONNECT`, NineLives, ротация IP) в этот репозиторий пока не выложены.

## age

Утилиты age и age-keygen собираются из одного исходника age: `go build filippo.io/age/cmd/age` и `go build filippo.io/age/cmd/age-keygen` (CGO_ENABLED=0, GOARCH под роутер, softfloat). В `ROUTER_BIN` нужны оба файла: `age-<arch>` и `age-keygen-<arch>`; сборка пакета без age-keygen прерывается.
