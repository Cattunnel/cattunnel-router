#!/usr/bin/env bash
# Ed25519 signature for latest.json (lib/feature/updates): the app only
# trusts a latest.json whose latest.json.sig verifies with the key it was
# built with (--dart-define=UPDATE_PUBKEY=…).
#
#   tools/sign_latest_json.sh genkey              # once; back the key up with the .jks
#   tools/sign_latest_json.sh pubkey              # value for --dart-define=UPDATE_PUBKEY
#   tools/sign_latest_json.sh sign latest.json    # writes latest.json.sig
#
# Upload latest.json.sig together with latest.json (the .sig first): a
# phone that sees a new latest.json with an old .sig just skips the check.
# Sign the exact file that gets uploaded - any later edit breaks it.
set -euo pipefail

KEY=${UPDATE_SIGNING_KEY:-$(dirname "$0")/update-signing.pem}

case ${1:-} in
genkey)
    [[ -e $KEY ]] && { echo "$KEY already exists - not overwriting" >&2; exit 1; }
    (umask 077 && openssl genpkey -algorithm ed25519 -out "$KEY")
    echo "created $KEY - back it up next to cattunnel-release.jks" >&2
    ;;
pubkey)
    # The raw key is the last 32 bytes of the DER SubjectPublicKeyInfo.
    openssl pkey -in "$KEY" -pubout -outform DER | tail -c 32 | base64 -w0
    echo
    ;;
sign)
    FILE=${2:?latest.json}
    openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$FILE" | base64 -w0 > "$FILE.sig"
    # Check it the way the app will, before it goes anywhere.
    openssl pkeyutl -verify -inkey "$KEY" -rawin -in "$FILE" -sigfile <(base64 -d "$FILE.sig") >/dev/null
    echo "wrote $FILE.sig" >&2
    ;;
*)
    sed -n '2,12p' "$0" >&2
    exit 1
    ;;
esac
