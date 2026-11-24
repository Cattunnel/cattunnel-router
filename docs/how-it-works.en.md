Русский: [how-it-works.md](how-it-works.md)

# How the router edition works

The router edition runs the same core as the CatTunnel app and takes servers from the same subscription. A watchdog, the script `cattunnel run`, manages the core. As in TrustTunnel, the client core ([TrustTunnelClient](https://github.com/TrustTunnel/TrustTunnelClient)) builds the connection to the server, while the router part handles the subscription, startup, checks and network rules.

```text
subscription (?format=router) --> cattunnel update --> servers.bundle
                                                           |
                                                           v
 settings cattunnel.conf --> cattunnel run --> client.toml --> engine
                                  |                              |
                                  +-- check every 30 s <---------+
                                  |
                                  +-- 4 failures in a row: next server
                                  +-- after 30 minutes: back to the chosen one
```

Figure 1. From the subscription to a running tunnel, and what the watchdog does.

## Subscription

`cattunnel update` downloads `<link>?format=router`: the subscription server returns the same servers as for the app, but as ready `[endpoint]` sections for the engine. The reply is encrypted for the router. `age` decrypts it (with the device key `device.key`, or the fallback `age.key` for older servers) and the result is stored in `servers.bundle`.

If the link does not answer, the router tries the mirrors from the previous subscription. The subscription refreshes itself when the file is older than 6 hours at startup, and then every 6 hours while the tunnel is up.

## Startup

`cattunnel run` builds the engine config `client.toml` from the chosen server's section and the current mode, and starts the engine in the foreground (under procd on OpenWrt, under `S99cattunnel` on Entware). In `socks` mode the config gets a SOCKS5 listener, in `tun` mode the `tt0` device with the MTU from the settings. The settings, subscription and config files are readable only by root (mode 600).

If the subscription asks for "Auto" anti-DPI, `run` tries methods 1, 2 and 3 in turn. The method remembered for the server goes first. Each method gets up to 15 seconds (`AUTO_WAIT`), and success is checked with a request through the tunnel. A method that works is saved and tried first next time. If the router itself has no internet, the methods are not rotated, because DPI is not the cause.

## Watchdog

Every 30 seconds (`CHECK_EVERY`) the watchdog checks the internet through the tunnel. After 4 failures in a row (`CHECK_FAILS`, which is 2 minutes) the chosen server counts as down, and with `FAILOVER on` the next server in subscription order is started. On a fallback server, every 30 minutes (`BACK_AFTER`) it tries to return to the chosen one.

If the router itself loses internet, servers are not rotated: the watchdog waits for the network for up to 5 minutes and then tries to connect anyway. If the engine crashes on its own, the watchdog first restarts the same server.

## Other parts

- Settings live in `/etc/cattunnel/cattunnel.conf`, and everything is under `/opt` on Entware. They are changed with `cattunnel set` (details in [settings.en.md](settings.en.md)).
- Your own sites and IPs go direct in `tun` mode: `cattunnel direct add|del|set|list|clear`.
- Updates: once a day the `install.sh` of the latest release is checked (Ed25519 signature). Use `cattunnel upgrade [check]`, or the "Update" button on the Status page.
- Autostart at boot survives a package reinstall: `cattunnel autostart on|off|status`.
- `cattunnel doctor` lists "router neighbors": other VPNs, proxies, DNS services, pbr and mwan3, memory and swap. `cattunnel nikki on|off|status` integrates CatTunnel into the nikki profile with a backup.

## Risks

- The engine size depends on the architecture and the TLS library. Recheck free space for every build, and check RAM use separately on models with 128 MB.
- Do not enable `tun` mode and nikki in `tun` mode together: two VPNs will fight over the routes.
