Русский: [build.md](build.md)

# Building the packages

Packages are built by `./build_packages.sh <version> [arch...]` into `build/`. Without an architecture list it builds aarch64, armv7 and mipsel. For x86_64 and mips, name the architecture explicitly.

```text
engine/build_router.sh        age, age-keygen
 (trusttunnel_client-<arch>)   (age-<arch>, age-keygen-<arch>)
          |                       |
          +-----------+-----------+
                      v
           ROUTER_BIN directory with the binaries
                      v
             ./build_packages.sh <version>
                      v
 build/: .ipk (OpenWrt, Entware), LuCI .ipk, .apk (if APK exists),
         install.sh, SHA256SUMS, .sig files (if a key is set)
```

Figure 1. How ready binaries become packages.

## Builder variables

- `ROUTER_BIN`: a directory with `trusttunnel_client-<arch>`, `age-<arch>` and `age-keygen-<arch>`. If any of the three is missing, the build stops.
- `ENGINE_LICENSE` and `AGE_LICENSE`: the license files of the engine and age that go into the package.
- `APK`: the path to `apk` from apk-tools 3 with the `mkpkg` command. Without it no `.apk` files are made, and the `.ipk` files are built as usual.
- `ROUTER_MIRRORS`: where the installer downloads packages from. The default is `https://github.com/Cattunnel/cattunnel-router/releases/latest/download`.
- `UPDATE_SIGNING_KEY`: the Ed25519 signing key. Without it the builder warns and leaves `install.sh` and `SHA256SUMS` without `.sig`.

The age version is not fixed in `build_packages.sh`: the package takes the ready binaries from `ROUTER_BIN`. Both age tools come from the same age source, so check their versions against it.

## The engine

`engine/build_router.sh` builds `trusttunnel_client` from [TrustTunnelClient](https://github.com/TrustTunnel/TrustTunnelClient) with the CatTunnel patches. It accepts only revision `b59debf4` (version `1.3.0-rc.1-57-gb59debf4`), the same core as in app 1.5.9.5. Any other revision in `TT_SRC` stops the build.

Without arguments the script builds aarch64, mipsel, armv7 and mips. Add x86_64 as an argument. The build is static (preset `musl-cross-<arch>-relwithdebinfo`) and needs zig 0.17.0, Conan 2.31.1 with the AdGuard recipes, Rust 1.95, CMake, Ninja and llvm-strip. For mips and mipsel it also needs the nightly Rust `5d8fec066 2026-10-16` with `rust-src`. The script will not start while cargo, cmake, ninja or gradle is running.

TLS library per architecture:

| Architectures | Library | What it means |
|---|---|---|
| aarch64, armv7, x86_64 | `openssl/boring-2026-05-08@adguard/oss` | custom client random and ML-DSA are available |
| mips, mipsel | `openssl/4.0.2@adguard/oss` | the `client_random_auth_key` key does not work |

Next to each binary the script writes `trusttunnel_client-<arch>.build.txt` with the revision, version, architecture, zig version, TLS library and SHA-256. That file shows what was actually built.

The patches in `engine/` (anti-DPI, a network monitor for policy routing, build fixes for NativeLibsCommon and DnsLibs) belong to earlier core versions. The other core changes up to `b59debf4`, including the connection pool, IP rotation and the Ed25519 fix for mips and mipsel, are not published here as separate patches. The differences from upstream are described in the [app documentation](https://github.com/Cattunnel/cattunnel/tree/main/docs).

## age

`age` and `age-keygen` run on the router to decrypt the subscription and to create the device key. The builder puts `age`, `age-keygen` and the age license (BSD 3-Clause) into the package, as in the original [age](https://github.com/FiloSottile/age).
