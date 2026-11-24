Русский: [testing.md](testing.md)

# Tests

The `tests/` directory holds two sets of checks: fast unit tests, and a container lab that checks installation, updates and network rules.

## Unit tests

```
python3 -m unittest discover -s tests -v
```

The tests run the real router scripts (`common/cattunnel`, `common/upgrade.sh`, `install.sh.in`) and curl, and replace the system boundaries with stubs. Neither Docker nor root is needed. If real `age` and `age-keygen` are in `PATH` (or `CATTUNNEL_TEST_AGE_DIR` is set), some tests use them, otherwise stubs stand in.

| File | What it checks |
|---|---|
| `test_device_key.py` | the device key and the one-time link exchange, subscription mirrors, decryption with the new and the fallback key, anti-DPI method choice, the router network check, building the engine config |
| `test_report.py` | `cattunnel report` is useful and never exposes the subscription, passwords or keys |
| `test_upgrade.py` | the temporary block during an update, rollback of files and the package database, installer locks, the difference between a plain stop and `stop --force` |
| `test_matrix_safety.py` | the lab's own safety checks |

## Container lab

The lab checks packages in isolated OpenWrt 24, OpenWrt 25 and Entware containers with no internet access. A small test engine with a real TUN and SOCKS5 stands in for the real engine. So the lab confirms the network rules and the service lifecycle, but not compatibility with a TrustTunnel server or speed on a real router.

```text
containers: OpenWrt 24, OpenWrt 25, Entware
   |                      |
 LAN client ---> router (CatTunnel package) ---> outside host and exit host
   |
 rule counters, WAN packet capture, direct HTTP reply
```

Figure 1. The lab: a client, a router and two outside hosts in isolated networks.

`tests/create_router_containers.sh` creates the containers from local images (`LAB_DIR`, `OW24_IMAGE`, `OW25_IMAGE`, `ENTWARE_IMAGE`, `ENDPOINT_IMAGE`). Before a run it checks that the containers are not privileged and have no `/dev/watchdog`. Then:

- `router_matrix.py` (needs root) runs through the platforms, `tun` and `socks` modes, empty and non-empty `DEVICES`, and ten operations: update, reinstall, restart, stop, remove, rollback, `stop --force`, remove during an update, reinstall of a stopped service and reinstall with autostart off. `--ipv6` checks IPv6, `--dns-cleanup` the DNS return, `--exchange-import` the one-time link import.
- `router_recovery.py` covers stuck locks and update markers, a killed installer process and a container restart.
- `router_tls.py <arch>` captures the ClientHello of the real engine under qemu-user toward a local address. It checks the packet that is sent, not a successful connection.

## Not tested

- ASUS Merlin: the package and commands are the same as for Entware on Keenetic, but there is no Merlin lab.
- Real routers: the lab runs on x86_64 in containers, and binaries for other architectures run only under qemu-user.
- Switching nikki to the fallback VLESS when CatTunnel fails.
- The installer messages "SHA-256 mismatch" and "mirror not answering" were read from the code, not reproduced.
