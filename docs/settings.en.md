Русский: [settings.md](settings.md)

# CatTunnel settings and modes on the router

- [Settings file and the set command](#settings-file-and-the-set-command)
- [Stopping and updating](#stopping-and-updating)
- [Two modes](#two-modes)
- [Only some devices through the tunnel](#only-some-devices-through-the-tunnel)
- [Russian sites direct](#russian-sites-direct)
- [Setup with nikki and mihomo](#setup-with-nikki-and-mihomo)
- [Web page on Keenetic and ASUS Merlin](#web-page-on-keenetic-and-asus-merlin)

## Settings file and the set command

Settings are stored in `/etc/cattunnel/cattunnel.conf`, and in `/opt/etc/cattunnel/cattunnel.conf` on Entware. UCI is not used. `cattunnel settings` shows the values and `cattunnel set NAME value` changes them. One call can take several pairs: `cattunnel set MODE tun KILLSWITCH on`.

Values are validated when written, and the engine parameters apply when the service restarts. Changing `MODE` does not start the service and does not change the external proxy profile.

| Group | Name and allowed values (default) |
|---|---|
| Mode and service | `MODE socks\|tun` (`socks`), `SOCKS <IPv4:port>` (`127.0.0.1:1080`), `TUN_DEV <name>` (`tt0`), `LOGLEVEL error\|warn\|info\|debug` (`info`), `SERVER <key>`, `SUB_URL <link>` |
| Routing | `KILLSWITCH on\|off` (`on`), `RU_DIRECT on\|off` (`on`), `DNS router\|tunnel` (`router`), `MTU 1200-1500` (`1350`), `DEVICES '<MACs or names separated by spaces>'` (empty), `IDLE_STOP <seconds>` (`600`) |
| Watchdog | `FAILOVER on\|off` (`on`), `AUTO_WAIT` (`15`), `CHECK_EVERY` (`30`), `CHECK_FAILS` (`4`), `BACK_AFTER` (`1800`), all in seconds except `CHECK_FAILS` |
| Subscription overrides | `OVR_TLS chrome\|firefox\|safari\|okhttp`, `OVR_DPI off\|1\|2\|3\|auto\|custom`, `OVR_DESYNC '<string>'`, `OVR_PADDING <number>` (up to 64), `OVR_QUIC on\|off` |
| Web page and integration | `WEB on\|off`, `WEB_PORT <number>` (`8090`), `NIKKI on\|off` |

The overrides are empty by default, and then the subscription value applies. For a single server there are `SRV_<key>_TLS`, `_DPI`, `_DESYNC`, `_PADDING` and `_QUIC`: an empty string inherits the common override, and `sub` returns the subscription value. `OVR_PADDING` sets the number of HTTP/2 frames with padding (`h2_padding_frames` in the engine config). Other engine defaults: 1 to 64 bytes per frame, 2048 bytes per stream and 4096 bytes per session. `OVR_QUIC on` blocks QUIC. The services are configured separately: `cattunnel web password\|on\|off\|status` and `cattunnel nikki on\|off\|status`.

## Stopping and updating

A normal stop (`cattunnel stop`, the init script, the "Stop" button) returns DNS and the device rules to direct access and keeps the settings and the subscription. A service restart and a server switch use an internal stop that keeps the block. While the `upgrade.pending` marker is active, a plain `stop` also keeps the protection. To leave explicitly during an unfinished update, use `cattunnel stop --force`, which the "Stop" buttons in LuCI and on the web page also call.

The installer lock stores a PID, a time and a boot identifier. If the process died or 15 minutes passed, the install can be repeated. The `upgrade.pending` marker also lasts 15 minutes. A finished installer waits up to 5 minutes for the connection and then lifts the temporary barrier. For a stopped service, and for Entware with `autostart.off`, the install barrier is not enabled.

## Two modes

| Mode | For whom | How it works |
|---|---|---|
| `socks` (default) | OpenWrt with mihomo or nikki | SOCKS5 on `127.0.0.1:1080` (TCP and UDP). mihomo decides what goes into CatTunnel, and routing, zapret and AdGuard Home stay as they were |
| `tun` | A router without an external proxy: OpenWrt without mihomo, Keenetic, ASUS Merlin | device `tt0`, the engine sets the routes, the whole LAN goes into the tunnel, local networks bypass it |

## Only some devices through the tunnel

`tun` mode, the `DEVICES` parameter.

```
cattunnel set MODE tun DEVICES 'aa:bb:cc:dd:ee:ff Phone*'   # MAC, a name or a name start with "*", separated by spaces
cattunnel firewall on && /etc/init.d/cattunnel restart       # Entware: /opt/etc/init.d/S99cattunnel restart
cattunnel devices status
```

With a non-empty `DEVICES` only the selected devices go into the tunnel, and the others keep the normal route. With an empty list the whole LAN uses the tunnel. In `socks` mode the external proxy sets the routing, and `DEVICES` only defines the scope of the temporary block during an update or restart.

`IDLE_STOP` is 600 seconds by default. While the selected devices make no internet requests the engine does not run, and after a period of silence it stops again. The first packet from a device starts the engine. `IDLE_STOP 0` turns off stopping on silence.

```text
device --> router: packet with a MAC from DEVICES --> mark 0x1801
                                                         |
                    routing table 218 <------------------+
                         |            |
               tt0 exists: tunnel     no: unreachable (kill switch)
```

Figure 1. How packets of the selected devices reach the tunnel.

Packets of the selected devices are marked by MAC: with the nftables table `inet cattunnel_dev` on OpenWrt and the iptables chain `CATTUNNEL_DEV` on Entware. The mark sends packets to routing table 218 that exits through `tt0`, with exceptions for local networks and an `unreachable` route when the kill switch is on. The rules apply to IPv6 as well.

Device names come from DHCP, and on Keenetic also from `ndmc show ip hotspot`. The watchdog rechecks them every 30 seconds. A name or a prefix with an asterisk lets the router find a phone after its private MAC changes. If the phone reports no name, use a permanent MAC. `cattunnel devices status` shows the result.

With `DNS tunnel` the port 53 requests of the selected devices go to the DNS from the subscription, and the DNS of other devices stays unchanged. In LuCI the list is set under "Settings → Only these devices".

## Russian sites direct

`tun` mode, the `RU_DIRECT` parameter (`on` by default).

`RU_DIRECT on` adds exceptions for Russian domains, the built-in service list and the geoip:ru networks. The built-in list is in `/usr/share/cattunnel/ru_services.txt` (Entware: `/opt/usr/share/cattunnel/ru_services.txt`). Downloaded networks are stored in `ru.cidr` and refreshed every 20 hours, and on a failure the previous list stays.

The engine applies the exceptions to traffic inside `tun`, including packets of the selected devices. Network exceptions do not need name resolution. `cattunnel ru status` shows the state, `cattunnel ru update` refreshes by hand, and `cattunnel set RU_DIRECT off` with a restart turns it off.

## Setup with nikki and mihomo

1. Install the package and the subscription as above. `socks` mode is the default.
2. `cattunnel mihomo` prints ready lines for the mihomo profile: the `CatTunnel` proxy (socks5, udp), a `VPN` group of type `fallback` (CatTunnel, then VLESS-REALITY) and `DIRECT` rules for the tunnel itself: the `trusttunnel_client` process and the CatTunnel server addresses. Put these rules first, or the engine's connection to the server will go into mihomo and loop back on itself.
3. Add `VPN` first to the `PROXY`, `YOUTUBE` and `FINAL` selectors and restart nikki (`service nikki restart`).
4. Check with `cattunnel test`. In LuCI on the Nikki page the `VPN` group should show CatTunnel as alive.

Instead of editing by hand you can run `cattunnel nikki on`: it integrates CatTunnel through the nikki mixin (group `CatTunnel-VPN`) and can roll back with `off`.

VLESS stays as the fallback exit of the `fallback` group, and mihomo checks availability. That is a mihomo setting, while `FAILOVER` switches servers inside the CatTunnel subscription. They are different things.

## Web page on Keenetic and ASUS Merlin

The native Keenetic web interface cannot be extended, so CatTunnel has its own page. It is the same LuCI pages (Status, Servers, Settings, Diagnostics), started through a small shim `www/luci-shim.js` instead of LuCI. The page commands go to `cgi-bin/api` with the same allowed list as the LuCI ACL.

```
cattunnel web password <password>    # 8 characters or more, user admin
cattunnel web on                     # then http://<router address>:8090
```

`lighttpd` with mod_cgi, mod_auth and mod_authn_file is installed automatically. It listens only on the router's home address (`br0` on Keenetic and Merlin, `br-lan` on OpenWrt), the port is open in the firewall only for the home network, and login needs a password. If port 8090 is busy, the nearest free one of the next ten is used. Changes are accepted only as a POST with the header `X-CatTunnel: 1`, and `cattunnel set` validates the values. On Keenetic the netfilter hook restores the rule after rebuilds.

The page shows the state, start and stop, the network devices with "through VPN" checkboxes, the server, the kill switch, Russian sites direct and the idle minutes. `cattunnel web off` turns the page off, and `cattunnel web status` shows its state.

On OpenWrt the pages are in LuCI: "Services → CatTunnel". A separate web page can also be enabled there with `cattunnel web on`.
