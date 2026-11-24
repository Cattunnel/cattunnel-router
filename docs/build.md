English: [build.en.md](build.en.md)

# Сборка пакетов

Пакеты собирает `./build_packages.sh <версия> [arch...]`. Результат кладётся в `build/`. Без списка архитектур собираются aarch64, armv7 и mipsel; для x86_64 и mips архитектуру нужно указать явно.

```text
engine/build_router.sh        age, age-keygen
 (trusttunnel_client-<arch>)   (age-<arch>, age-keygen-<arch>)
          |                       |
          +-----------+-----------+
                      v
          каталог ROUTER_BIN с бинарниками
                      v
             ./build_packages.sh <версия>
                      v
 build/: .ipk (OpenWrt, Entware), LuCI .ipk, .apk (если есть APK),
         install.sh, SHA256SUMS, подписи .sig (если есть ключ)
```

Рисунок 1. Как из готовых бинарников получаются пакеты.

## Переменные сборщика

- `ROUTER_BIN`: каталог с `trusttunnel_client-<arch>`, `age-<arch>` и `age-keygen-<arch>`. Без любого из трёх файлов сборка прерывается.
- `ENGINE_LICENSE` и `AGE_LICENSE`: файлы лицензий движка и age, которые кладутся в пакет.
- `APK`: путь к `apk` из apk-tools 3 с командой `mkpkg`. Если файла нет, `.apk` не создаются, а `.ipk` собираются как обычно.
- `ROUTER_MIRRORS`: адреса, с которых установщик скачивает пакеты. По умолчанию это `https://github.com/Cattunnel/cattunnel-router/releases/latest/download`.
- `UPDATE_SIGNING_KEY`: закрытый ключ подписи Ed25519. Если ключа нет, сборщик предупреждает и оставляет `install.sh` и `SHA256SUMS` без `.sig`.

Версия age не задана в `build_packages.sh`: в пакет попадают готовые бинарники из `ROUTER_BIN`. Утилиты age и age-keygen берутся из одного исходного пакета age, поэтому их версии нужно сверять с ним самим.

## Движок

Скрипт `engine/build_router.sh` собирает `trusttunnel_client` из [TrustTunnelClient](https://github.com/TrustTunnel/TrustTunnelClient) с патчами CatTunnel. Он принимает только ревизию `b59debf4` (версия `1.3.0-rc.1-57-gb59debf4`), то же ядро, что в приложении 1.5.9.5. Другая ревизия в `TT_SRC` останавливает сборку.

Без аргументов скрипт собирает aarch64, mipsel, armv7 и mips. x86_64 добавляется аргументом. Сборка статическая (пресет `musl-cross-<arch>-relwithdebinfo`), для неё нужны zig 0.17.0, Conan 2.31.1 с рецептами AdGuard, Rust 1.95, CMake, Ninja и llvm-strip. Для mips и mipsel нужен nightly Rust `5d8fec066 2026-10-16` с `rust-src`. Две сборки одновременно скрипт не запускает: он отказывается стартовать, пока идут cargo, cmake, ninja или gradle.

Какая библиотека TLS используется:

| Архитектуры | Библиотека | Что это значит |
|---|---|---|
| aarch64, armv7, x86_64 | `openssl/boring-2026-05-08@adguard/oss` | есть пользовательский client random и ML-DSA |
| mips, mipsel | `openssl/4.0.2@adguard/oss` | ключ `client_random_auth_key` не работает |

Рядом с каждым бинарником скрипт пишет `trusttunnel_client-<arch>.build.txt`: ревизия, версия, архитектура, версия zig, библиотека TLS и SHA-256. По этому файлу видно, что именно собрано.

Патчи в `engine/` (анти-DPI, монитор сети для policy routing, правки сборки NativeLibsCommon и DnsLibs) относятся к более ранним версиям ядра. Остальные изменения ядра до `b59debf4`, в том числе пул соединений, ротация IP и исправление Ed25519 для mips и mipsel, в этот репозиторий отдельными патчами не выложены. Различия с upstream описаны в [документации приложения](https://github.com/Cattunnel/cattunnel/tree/main/docs).

## age

`age` и `age-keygen` нужны на роутере для расшифровки подписки и создания ключа устройства. Сборщик кладёт в пакет `age`, `age-keygen` и их лицензию (BSD 3-Clause), как в оригинальном [age](https://github.com/FiloSottile/age).
