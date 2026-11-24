# CatTunnel for routers

Русский: [README.md](README.md)

CatTunnel for routers is the router edition of the [CatTunnel](https://github.com/Cattunnel/cattunnel) VPN client for **OpenWrt** (23.05, 24.10, 25.x; pages in LuCI), **Keenetic** and **ASUS Merlin** (Entware; its own web page). It covers devices where the app cannot be installed (TV, set-top box, console) and uses the same network core and the same subscription as the app. Control: the `cattunnel` command, LuCI pages or the web page.

## CatTunnel repositories

| Repository | What it is |
|---|---|
| [Cattunnel/cattunnel](https://github.com/Cattunnel/cattunnel) | App for Android, Windows and Linux |
| [Cattunnel/cattunnel-router](https://github.com/Cattunnel/cattunnel-router) | Router edition for OpenWrt, Keenetic and ASUS Merlin (this repository) |
| [Cattunnel/cattunnel-server](https://github.com/Cattunnel/cattunnel-server) | Server: a fork of the TrustTunnel endpoint with the NineLives transport |

## Features

**Modes**

| Mode | For whom | How it works |
|---|---|---|
| `socks` (default) | OpenWrt with mihomo/nikki (the nikki + mihomo setup) | SOCKS5 on `127.0.0.1:1080` (TCP and UDP). mihomo itself decides what to send into CatTunnel; routing, zapret and AdGuard Home stay as they were |
| `tun` | A router without an external proxy: OpenWrt without mihomo, Keenetic, ASUS Merlin | device `tt0`, the engine sets up the routes, the whole LAN or selected devices go into the tunnel (local networks bypass it) |

**Connection and blocking bypass** (the same core as in app 1.5.9.5, revision `b59debf4`)

- Anti-DPI: methods 1-3, "Auto" (trying each for 15 s with an internet check, the method that worked is remembered for the server) and a custom string in ByeDPI syntax.
- TLS fingerprint: `chrome`, `firefox`, `safari`, `okhttp`.
- HTTP/2 size masking (the number of frames with padding; the other parameters are taken from the core defaults) and QUIC blocking.
- Connection pool: 2-4 TLS connections to the server and a 2-6 s pause between handshakes instead of a burst at start.
- The server name (SNI) and other parameters come from the subscription as ready sections for the engine.
- All of this is set by the subscription; the router can override the values with common (`OVR_*`) or per-server (`SRV_<key>_*`) settings.
- Not supported yet: the NineLives transport and the "Chrome 156" profile. The TLS authorization key `client_random_auth_key` does not work on mips/mipsel (the core there is built with OpenSSL); access is determined by login and password.

**Subscription**

- Import of a one-time link from the subscription server (`/api/go/<code>`) or `cattunnel://subscription?code=...&base=...`: the router exchanges the code for permanent subscription addresses bound to its public key. The previous permanent link is also supported.
- On import or the first update the router creates its own age device key (`device.key`) and sends the public part to the server. The user's old key (`age.key`) stays as a fallback for older servers; the one-time code is not written to the settings.
- The subscription server must return the list in the router format (`?format=router`, the line `# cattunnel-router 1` at the start). If the download fails, the router tries the mirrors from the previous subscription. The subscription format in the app: [docs/subscriptions.md](https://github.com/Cattunnel/cattunnel/blob/main/docs/subscriptions.md).

**Network and reliability**

- Kill switch is on by default, including for each selected device.
- Selected devices only (`DEVICES`: MAC, DHCP name or a name prefix with "*"), tunnel on demand: the engine starts with the first packet from a selected device and stops after 10 minutes of silence (`IDLE_STOP`).
- Russian sites directly (`RU_DIRECT`): domains, a built-in service list and geoip:ru networks, refreshed every 20 hours.
- Watchdog: a tunnel check every 30 s, a switch to the next subscription server after 2 minutes without a reply, and an attempt to switch back every 30 minutes.
- Strict certificate checking: the set of roots is built from the router's bundle without the Russian root.
- Update: once a day the `install.sh` of the latest release is checked, with an Ed25519 signature; `cattunnel upgrade` rolls back on error.

## Installation

```
curl -fsSLO https://github.com/Cattunnel/cattunnel-router/releases/latest/download/install.sh && sh install.sh
```

The installer picks the package by system and processor, and checks memory, kernel, free space and the SHA-256 of the downloaded files. The first command downloads `install.sh` over HTTPS; verifying its signature is done separately ([docs/install.en.md](docs/install.en.md#signature-check)), and during `cattunnel upgrade` it is mandatory.

Packages by architecture, offline installation, manual installation on OpenWrt, Keenetic and ASUS Merlin: [docs/install.en.md](docs/install.en.md).

## Setup

```
cattunnel import '<subscription link>'   # the device key is created automatically
cattunnel list                       # servers; * - selected
cattunnel use <key>                 # select a server from "cattunnel list"
/etc/init.d/cattunnel start          # Keenetic / Merlin: /opt/etc/init.d/S99cattunnel start
cattunnel test                       # "ok: internet through the tunnel works"
```

`tun` mode on OpenWrt without an external proxy: `cattunnel set MODE tun && cattunnel firewall on && /etc/init.d/cattunnel restart`.

Settings are stored in `/etc/cattunnel/cattunnel.conf` (Entware: `/opt/etc/cattunnel/cattunnel.conf`); `cattunnel settings` shows them, `cattunnel set NAME value` changes them. The list of settings, devices through the VPN, Russian sites directly, integration with nikki/mihomo and the web page: [docs/settings.en.md](docs/settings.en.md).

On OpenWrt the pages are in LuCI: "Services → CatTunnel". On Keenetic and ASUS Merlin: `cattunnel web password <password>`, then `cattunnel web on` and `http://<router address>:8090`.

## Building

`./build_packages.sh <version> [arch...]` builds the packages into `build/` from ready core binaries (`engine/build_router.sh`) and a static age. Details: [docs/build.en.md](docs/build.en.md).

## Documentation

| File | What it covers |
|---|---|
| [docs/install.en.md](docs/install.en.md) | Packages, install.sh, OpenWrt, Keenetic, ASUS Merlin, signature verification |
| [docs/settings.en.md](docs/settings.en.md) | Settings, modes, devices, Russian sites, nikki/mihomo, web page |
| [docs/how-it-works.en.md](docs/how-it-works.en.md) | Subscription, engine start, watchdog, update; risks |
| [docs/build.en.md](docs/build.en.md) | Building packages, the core and age |
| [docs/testing.en.md](docs/testing.en.md) | Tests and the container lab |
| [help/ROUTER.en.md](help/ROUTER.en.md) | The help that is installed together with the package |

## What's new

**1.5.9.5**
- The core is the same revision as app 1.5.9.5 (`b59debf4`): IP rotation. If the next server does not
  answer or refuses, it rests and the tunnel stays on the current one; when every server rests, the next
  attempt waits for the end of the nearest rest instead of a reconnect storm.

**1.5.9**
- The core is the same revision as app 1.5.9 (`82963908`): 2-4 TLS connections to the server and a 2-6 s
  pause between handshakes instead of a burst at start.
- Reliable update: the lock remembers the process, time and router boot, an unfinished update
  (`upgrade.pending`) is reset after 15 minutes; `cattunnel stop --force` leaves it while keeping
  the settings and subscription; a rollback removes the files of the new package that were not in the backup.
- The NineLives transport and the "Chrome 156" profile cannot be configured in the router version yet.

**1.5.5**
- The core with the patch `0002-network-monitor-policy-routing.patch`. The network monitor in the core looked for the
  default route only in the `main` table; where routes are laid out in their own tables (`ip rule`: mwan3,
  pbr, custom setups), after any change of addresses or routes the engine decided "no network" and waited for it
  forever: the watchdog saw a dead tunnel and cycled through servers. Now the engine asks the kernel itself
  whether there is a route to the internet, and reconnects only if the exit address changed. On ordinary
  OpenWrt, Keenetic and Merlin the behavior is the same as before.

**1.5.4**
- The watchdog no longer crashes on a fresh install (before any update check had happened):
  it used to cause a reconnect every ~37 s. The same pattern is fixed in the nikki handling.

**1.5.3**
- No orphaned engines: on stop the watchdog kills its own engine, and extra engines
  are killed before every start. `install.sh --from <folder>` installs without internet.
  `cattunnel doctor`: clearer about memory, swap and zram.

## License

Apache License 2.0, see [LICENSE](LICENSE). The packages include `trusttunnel_client` (a build of AdGuard's TrustTunnelClient, Apache-2.0, with CatTunnel patches) and age (BSD 3-Clause); details and third-party licenses are in [NOTICE](NOTICE). CatTunnel is not affiliated with AdGuard; "TrustTunnel" and "AdGuard" are trademarks of their owners.
