#!/usr/bin/env bash
# Router engine: 1.3.0-rc.1-21-g8d58a15d, release/1.5.7; revision 8d58a15de3e0c1e5936bbad51baedff94ceedbf3.
# Android 1.5.8 / router builds of 31 October used its parent 4514f9f1
# (1.3.0-rc.1-20-g4514f9f1). This revision adds the MIPS Ed25519 EVP fix.
# SSL from conanfile.py: aarch64/armv7/x86_64 use
# openssl/boring-2026-05-08@adguard/oss (custom client random and ML-DSA);
# mips/mipsel use openssl/4.0.2@adguard/oss, without custom client random.
# Moving MIPS to BoringSSL requires a separate recipe/integration change.
#
# TT_SRC=/path/to/engine TT_BUILD_ROOT=/path/to/build engine/build_router.sh [arch...]
# Default architectures: aarch64 mipsel armv7 mips. Add x86_64 explicitly.
# Requires zig 0.17.0, Conan 2.31.1 with the matching AdGuard recipes,
# Rust 1.95 (MIPS: nightly 5d8fec066 2026-10-16 with rust-src), CMake,
# Ninja and llvm-strip. Use an already prepared Conan cache
# and provider from native_libs_common/8.1.54 (zig wrapper support).
set -euo pipefail
B=${TT_BUILD_ROOT:-$HOME/tt-build}
SRC=${TT_SRC:-$B/TTC-beta}
OUT=${TT_OUT:-$B/router-bin}
REV=8d58a15de3e0c1e5936bbad51baedff94ceedbf3
VERSION=1.3.0-rc.1-21-g8d58a15d
JOBS=${TT_JOBS:-2}
# Never download a missing toolchain implicitly during a router build.
export RUSTUP_AUTO_INSTALL=0
MIPS_RUST='rustc 1.101.0-nightly (5d8fec066 2026-10-16)'
command -v git >/dev/null || { echo 'git is required to verify engine revision' >&2; exit 1; }
[ "$(git -C "$SRC" rev-parse HEAD)" = "$REV" ] || { echo "Expected engine revision $REV" >&2; exit 1; }
# Avoid overlapping another heavyweight build on the 7.5 GiB build host.
if pgrep -ax 'cargo|cmake|ninja|gradle|GradleDaemon' >&2; then
    echo 'Another build is running; wait for it before building the router engine' >&2
    exit 1
fi
mkdir -p "$B" "$OUT"
mkdir "$B/router-build.lock" 2>/dev/null || { echo "Build lock exists: $B/router-build.lock" >&2; exit 1; }
trap 'rmdir "$B/router-build.lock"' EXIT
STRIP=$(command -v llvm-strip || command -v llvm-strip-19)
export ZIG_GLOBAL_CACHE_DIR=${ZIG_GLOBAL_CACHE_DIR:-$B/zig-cache}
if [ "$#" = 0 ]; then set -- aarch64 mipsel armv7 mips; fi
for A in "$@"; do
    case "$A" in aarch64|armv7|mips|mipsel|x86_64) ;; *) echo "Unknown architecture: $A" >&2; exit 1 ;; esac
    case "$A" in mips*)
        [ "$(rustup run nightly rustc --version)" = "$MIPS_RUST" ] || {
            echo "MIPS requires the installed toolchain: $MIPS_RUST" >&2; exit 1;
        }
        nightly_root=$(rustup run nightly rustc --print sysroot) || {
            echo 'MIPS requires installed nightly Rust and rust-src for -Zbuild-std' >&2; exit 1;
        }
        [ -f "$nightly_root/lib/rustlib/src/rust/library/Cargo.toml" ] || {
            echo 'MIPS nightly is missing rust-src (library/Cargo.toml)' >&2; exit 1;
        } ;;
    esac
    D=$B/cmake-build-musl-cross-$A-relwithdebinfo
    LOG=$B/router_$A.log
    echo "Building $A; log: $LOG"
    make -C "$SRC" PRESET="musl-cross-$A-relwithdebinfo" BUILD_DIR="$D" \
        SKIP_BOOTSTRAP=1 SKIP_VENV=1 NPROC="$JOBS" \
        CMAKE_ARGS='-DCONAN_HOST_PROFILE="zigbase;auto-cmake"' \
        build_trusttunnel_client >"$LOG" 2>&1
    binary=$D/trusttunnel/trusttunnel_client
    grep -qa "$VERSION" "$binary" || { echo "$A: wrong engine version, expected $VERSION" >&2; exit 1; }
    grep -qa 'Anti-DPI mode' "$binary" || { echo "$A: missing anti-DPI support" >&2; exit 1; }
    "$STRIP" -o "$OUT/trusttunnel_client-$A" "$binary"
    { echo "revision=$REV"; echo "version=$VERSION"; echo "arch=$A"; echo "zig=$(zig version)";
      case "$A" in mips*) echo "rust=$MIPS_RUST"; echo 'ssl=openssl/4.0.2@adguard/oss' ;; *) echo 'ssl=openssl/boring-2026-05-08@adguard/oss' ;; esac
      sha256sum "$OUT/trusttunnel_client-$A";
    } > "$OUT/trusttunnel_client-$A.build.txt"
    ls -l "$OUT/trusttunnel_client-$A"
done
(cd "$OUT" && sha256sum trusttunnel_client-* | grep -v '\.build\.txt$' > SHA256SUMS)
