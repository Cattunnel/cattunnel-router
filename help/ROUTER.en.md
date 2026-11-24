Русский: [ROUTER.ru.md](ROUTER.ru.md)

# CatTunnel on a router

CatTunnel on a router runs TrustTunnel with CatTunnel patches and takes servers from the same subscription as the app. On OpenWrt it is managed in LuCI under "Services → CatTunnel", and on Keenetic and ASUS Merlin through Entware and a separate web page.

## Quick start

1. Install the package over SSH: `curl -fsSLO https://github.com/Cattunnel/cattunnel-router/releases/latest/download/install.sh && sh install.sh`. The installer picks the system and architecture, checks resources and the package SHA-256, and explains the reason if the router does not fit.
2. Add the one-time link from the subscription server under "Settings → Subscription" or run `cattunnel import '<link>'`. Links like `/api/go/<code>` and `cattunnel://subscription?code=...&base=...` are exchanged for a permanent subscription address bound to the router's public key, and the one-time code is not stored. A permanent link also works. The user's old key can be skipped by pressing Enter or passed as the second argument: `cattunnel import '<link>' '<key>'`.
3. Choose a server on the "Servers" tab and press "Start" on the "Status" tab. The availability check is on the same page and runs as `cattunnel test`.

A separate page is enabled with `cattunnel web password <password>` and `cattunnel web on`; the password must have at least 8 characters. The page opens at `http://<router address>:8090` with the user name `admin`. These commands work on OpenWrt too.

## Modes

`socks` mode is the default: CatTunnel provides SOCKS5 for mihomo, nikki or another proxy. The external proxy sets the routing in this setup, so the CatTunnel Russian exceptions and the usual `DEVICES` rules do not change it in `socks` mode. The `DEVICES` list there only limits the scope of the temporary block during an update or restart.

`tun` mode creates the `tt0` device and sends the LAN traffic and the router's own traffic through it, keeping direct access to local networks and the set exceptions. Choose it with `cattunnel set MODE tun` and restart the service. A non-empty "Settings → Only these devices" list limits the tunnel to the chosen devices.

With nikki installed, the "Integrate into nikki" button adds CatTunnel to its groups and keeps the existing VLESS as the fallback exit. `cattunnel nikki off` returns the saved profile byte for byte if it was not changed after the integration, and restores the mixin and the previous group choice. If the profile was edited separately, CatTunnel removes only its own lines and keeps the other changes. The backup stays in the profiles directory.

## Devices through the VPN

With a non-empty `DEVICES` the tunnel works on demand: the first packet from a chosen device starts the engine, and 600 seconds of silence stop it by default. The time is set by `IDLE_STOP`. The value 0 keeps the tunnel always up, and an empty `DEVICES` sends the whole LAN through it.

For a phone with a private MAC, list the name it reports to the router. A prefix with an asterisk also works, for example `Phone*`. The watchdog rechecks names every 30 seconds. If there is no name, set a permanent MAC in the phone's Wi-Fi settings.

For the chosen devices the kill switch keeps a blocking route while the tunnel comes up or is down. With `DNS tunnel` the port 53 requests of these devices go to the DNS from the subscription, and the DNS of the other devices stays unchanged.

## Russian sites

`RU_DIRECT on` adds direct exceptions for Russian domains, the built-in service list and the geoip:ru networks. The engine applies the exceptions in `tun` mode, including the traffic of the chosen devices. In `socks` mode the external proxy uses its own rules.

The networks are downloaded from the runetfreedom and ipverse lists every 20 hours, and on a failure the previous list stays. `cattunnel ru status` shows the state and `cattunnel ru update` refreshes by hand. To turn it off, use the settings or `cattunnel set RU_DIRECT off` and restart the tunnel.

## Your own sites and IPs direct

The list "Settings → Sites and IPs direct" sets extra exceptions for `tun` mode, including when single devices are chosen. Each line holds a domain, a subdomain pattern with an asterisk, an IP address or a network. From the console, change the list with `cattunnel direct add|del|set|list|clear`, then restart the tunnel.

## Servers

The subscription refreshes every 6 hours, and if the first address is unreachable, the saved mirrors are used. If the chosen server fails 4 checks in a row at 30 second intervals, `FAILOVER on` moves the connection to the next subscription server, and after 30 minutes the watchdog tries to return to the chosen one.

If the router itself loses internet, the watchdog waits for the network and keeps the current server choice. `CHECK_EVERY`, `CHECK_FAILS` and `BACK_AFTER` change the check and return intervals. These values belong to the CatTunnel watchdog, and a fallback inside a mihomo group is configured separately.

Anti-DPI supports methods 1, 2 and 3, a custom desync string and the "Auto" mode, which tries methods 1-3 for 15 seconds each and remembers the one that worked for the server. Per-server settings override the TLS fingerprint, anti-DPI, the desync string, size masking and QUIC. By default the engine pads 1 to 64 bytes per frame, with budgets of 2048 bytes per stream and 4096 bytes per session. By default the subscription values are used. The mechanisms are described in "How the connection works".

## Safety

The kill switch is on by default and restricts the traffic sent to CatTunnel, keeping the explicitly set direct exceptions. When a running service is updated through `install.sh`, a separate temporary block limits the traffic of the chosen `DEVICES` until the tunnel check passes or the recovery time runs out. Other devices keep direct access, and with an empty `DEVICES` the whole LAN is blocked.

Stopping with `cattunnel stop`, the init script or the "Stop" button returns direct internet: the device rules and the kill switch are lifted, DNS is restored, and the settings and the subscription stay. During an unfinished update a plain stop keeps the protection. `cattunnel stop --force` and the "Stop" button lift it explicitly, while `restart` and failover keep the block.

Certificates are checked against the router's set of root authorities, from which CatTunnel removes the Russian Trusted Root and Sub CA and the Ministry of Digital Development authorities. This filtering applies to the engine connections and to the subscription download. The first `install.sh` download command uses curl's ordinary HTTPS check.

The subscription and the keys are in the CatTunnel directory, readable only by root. An update keeps `device.key`, and deleting it makes the server create a new device. The user's old key stays as a fallback for compatible older servers.

The installer verifies the package by the SHA-256 in its own text, and `cattunnel upgrade` also verifies the `install.sh.sig` signature with the Ed25519 key from the package. The first `curl ... && sh install.sh` does not verify the signature by itself. For a separate check on a PC, see docs/install.md.

The `upgrade.pending` marker lasts 15 minutes, after which the temporary barrier is lifted at the next watchdog check or management command. The lock's liveness is checked by PID, time and boot identifier. After the installer finishes it waits for tunnel confirmation for up to 5 minutes, and with autostart off on Entware or a stopped service the install barrier is not enabled.

A new version is checked once a day and shown as the "Update" button on the Status page. `cattunnel upgrade check` and `cattunnel upgrade` check and install the update. If needed, openssl is installed, a package manager failure rolls back the saved files, and the backup needs extra space in `/tmp`.

The web page listens on the router's home address and requires a password, stored as a SHA-512 hash when openssl is present and as MD5-crypt otherwise. A new password is set with `cattunnel web password <new>`, and the service autostart with `cattunnel autostart on|off|status`. The autostart choice survives a reinstall through the installer.

## What the router contacts by itself

The router stores the subscription, the keys and the device identifier, the settings, the direct exception lists and the root certificates. Service files hold the update state and the backups of the nikki integration. The engine log is capped at 256 KB, kept in memory and lost on reboot.

The tunnel check requests `connectivitycheck.gstatic.com/generate_204`. The router network check uses the provider DNS with a `ya.ru` query, plus fallback checks of 77.88.8.8, 1.1.1.1 and 8.8.8.8. The Russian network lists come from `cdn.jsdelivr.net` and `raw.githubusercontent.com` (runetfreedom/geoip and ipverse/rir-ip). The installer and its signature come from the package mirrors, by default the releases of `github.com/Cattunnel/cattunnel-router`.

When the subscription is imported or refreshed, its server receives the public key and a random device identifier, the package version and platform details. The release check downloads the installer and its signature. No analytics are used.

## Technical details

The engine build is pinned to TrustTunnelClient revision `b59debf4`: the same core as in Android 1.5.9.5 (IP rotation without drops), with the Ed25519 fix for MIPS. On aarch64, armv7 and x86_64 it uses BoringSSL `boring-2026-05-08` with the TLS authorization key and ML-DSA. mips and mipsel still use OpenSSL 4.0.2 without support for the TLS authorization key `client_random_auth_key`.

`engine/build_router.sh` sets a static musl build, and the build report tells whether each binary is ready. Installation needs Linux 3.2 or newer and 64 MB of memory, and `tun` also needs `/dev/net/tun`.

The installer chooses aarch64, armv7, mipsel or x86_64. The builder also supports mips big-endian, which the automatic installer rejects for now. OpenWrt 23.05/24.10 and Entware use `.ipk`, and OpenWrt 25 uses `.apk`.

Settings are in `/etc/cattunnel/cattunnel.conf`, and in `/opt/etc/cattunnel/cattunnel.conf` on Entware. `cattunnel settings` shows the values, and `set` takes several pairs, for example `cattunnel set MODE tun KILLSWITCH on`. Engine parameters apply after the service restarts.

- State and check: `cattunnel status`, `cattunnel test`, `cattunnel devices status`, `cattunnel ru status`.
- Servers and settings: `cattunnel list`, `cattunnel use <key>`, `cattunnel settings`, `cattunnel set <name> <value>`.
- Diagnostics: `cattunnel log 100`, `cattunnel report`, `cattunnel doctor`.
- Update and start: `cattunnel upgrade check`, `cattunnel upgrade`, `cattunnel autostart on|off|status`.

## If something does not work

The "Check internet through the tunnel" button on the Status tab or `cattunnel test` checks the connection. The log is under "Diagnostics", and `cattunnel doctor` shows "Router neighbors": other VPNs, proxies, DNS services, pbr/mwan3, memory and swap. `cattunnel doctor --apply` applies the suggested integration. Since version 1.5.5 the engine's network monitor accounts for routes in separate mwan3/pbr tables.

If a device does not reach the tunnel, `cattunnel devices status` shows the names found and the rules installed. If Russian sites are unavailable, check `RU_DIRECT` and `cattunnel ru status`.

To contact an administrator, use `cattunnel report`: it is anonymized and does not export the subscription or keys. `cattunnel log 100` prints an extra log, and passwords from the engine config are not added to it.
