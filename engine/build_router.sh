#!/usr/bin/env bash
# Наш trusttunnel_client (v1.3.0-beta.1 + 0001-anti-dpi-desync.patch) для роутеров:
# статические musl-сборки через zig, как официальные linux-<arch> релизы AdGuard
# (пресеты musl-cross-<arch> из их CMakePresets.json).
#
#   engine/build_router.sh [arch...]     # по умолчанию: aarch64 mipsel armv7
#   arch: x86_64 aarch64 armv7 mips mipsel
#   Результат: ~/tt-build/router-bin/trusttunnel_client-<arch> (без отладочной информации)
#
# Нужно один раз (проверено 05.10.2026):
#   - zig 0.17.0 в ~/development/zig-x86_64-linux-0.17.0 (ziglang.org, sha256 сверить);
#   - conan 2.31.1 и кэш ~/tt-build/conan-home, как для build_linux.sh;
#   - зависимости AdGuard из исходников, а их собственные conan-провайдеры не узнают
#     zig-обёртку (`<triple>-c++`) во вложенной сборке и добавляют -stdlib=..., который
#     zig отвергает. Поэтому:
#       NativeLibsCommon v8.1.52 (~/tt-build/nlc) + nlc-8.1.52-zig-wrapper.patch,
#         NLC_FROM_WORKTREE=1 conan export . --user adguard --channel oss --version 8.1.52
#       DnsLibs v2.10.2 (~/tt-build/dnslibs) + dnslibs-2.10.2-worktree.patch, в него
#         cmake/conan_provider.cmake = исправленный из NLC и conan/ из conanfiles.tar.gz
#         релиза NLC v8.1.52 (git add -f), затем
#         DNSLIBS_FROM_WORKTREE=1 conan export . --user adguard --channel oss --version 2.10.2
#   - профиль хоста без libcxx (наш default под x86_64 держит libstdc++11), он же
#     передаётся во вложенные сборки:
#       ~/tt-build/conan-home/profiles/zigbase:
#         [settings]
#         os=Linux
#         [conf]
#         tools.cmake.cmaketoolchain:extra_variables={'CONAN_HOST_PROFILE': 'zigbase;auto-cmake'}
# Первая сборка под архитектуру ~30–40 мин (зависимости), потом минуты.
set -euo pipefail
B=~/tt-build
SRC=${TT_SRC:-$B/TTC-clean}           # чистое дерево: тег + 0001-anti-dpi-desync.patch
OUT=$B/router-bin
export PATH=$HOME/development/zig-x86_64-linux-0.17.0:$B/conan/bin:$HOME/.cargo/bin:$PATH
export CONAN_HOME=$B/conan-home
STRIP=$(command -v llvm-strip || command -v llvm-strip-19)
mkdir -p "$OUT"
cd "$SRC"
for ARCH in "${@:-aarch64 mipsel armv7}"; do
  for A in $ARCH; do
    D=cmake-build-musl-cross-$A-relwithdebinfo
    echo "== $A"
    [ -f "$D/CMakeCache.txt" ] || cmake --preset "musl-cross-$A-relwithdebinfo" -B "$D" \
        -DCONAN_HOST_PROFILE="zigbase;auto-cmake" >"$B/router_$A.log" 2>&1
    cmake --build "$D" --target trusttunnel_client -j6 >>"$B/router_$A.log" 2>&1
    grep -qa "Anti-DPI mode" "$D/trusttunnel/trusttunnel_client" || { echo "$A: no anti-DPI patch inside" >&2; exit 1; }
    "$STRIP" -o "$OUT/trusttunnel_client-$A" "$D/trusttunnel/trusttunnel_client"
    ls -la "$OUT/trusttunnel_client-$A"
  done
done
(cd "$OUT" && sha256sum trusttunnel_client-* > SHA256SUMS)
