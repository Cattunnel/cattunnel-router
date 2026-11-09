#!/bin/sh
# Local isolated lab only. Supply locally prepared images; no external ports.
# Usage: LAB_DIR=/absolute/lab OW24_IMAGE=... OW25_IMAGE=... ENTWARE_IMAGE=... ENDPOINT_IMAGE=... sh tests/create_router_containers.sh
set -eu
: "${LAB_DIR:?set LAB_DIR to the lab directory}"
: "${OW24_IMAGE:?set the local OpenWrt 24 image}"
: "${OW25_IMAGE:?set the local OpenWrt 25 image}"
: "${ENTWARE_IMAGE:?set the local Debian+Entware image}"
: "${ENDPOINT_IMAGE:?set the local endpoint image with sleep}"
case "$LAB_DIR" in /*) ;; *) echo 'LAB_DIR must be absolute' >&2; exit 1 ;; esac
create() {
    name=$1; image=$2; shift 2
    docker create --name "$name" --hostname "$name" --network none --pull never \
        --cap-add NET_ADMIN --cap-add NET_RAW --device /dev/net/tun \
        --mount "type=bind,src=$LAB_DIR,dst=/lab" "$image" "$@"
    # Inspect before starting procd: a privileged container must never boot.
    python3 -c 'import sys; from router_matrix import inspect_safety; inspect_safety(sys.argv[1])' "$name"
    docker start "$name"
}
cd "$(dirname "$0")"
create ct159-ow24 "$OW24_IMAGE" /sbin/init
create ct159-ow25 "$OW25_IMAGE" /sbin/init
create ct159-entware "$ENTWARE_IMAGE" sleep infinity
for name in ct159-client ct159-outside ct159-exit; do
    create "$name" "$ENDPOINT_IMAGE" sleep infinity
done
python3 -c 'from router_matrix import preflight; preflight()'
