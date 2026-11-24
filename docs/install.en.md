Русский: [install.md](install.md)

# Installing CatTunnel on a router

- [Which package you need](#which-package-you-need)
- [One command (install.sh)](#one-command-installsh)
- [OpenWrt 23.05 / 24.10 (opkg) and 25.x (apk)](#openwrt-2305--2410-opkg-and-25x-apk)
- [Keenetic (Entware)](#keenetic-entware)
- [ASUS Merlin (Entware)](#asus-merlin-entware)
- [Signature check](#signature-check)

## Which package you need

`uname -m` shows the router CPU, and for MIPS the byte order comes from `opkg print-architecture`. The builder can make a mips big-endian package, but `install.sh` rejects such a system for now.

| File | For |
|---|---|
| `cattunnel_<ver>_openwrt-aarch64.ipk` | OpenWrt, `uname -m` is `aarch64` |
| `cattunnel_<ver>_openwrt-mipsel.ipk` | OpenWrt, MIPS little-endian (package architecture `mipsel_*`) |
| `cattunnel_<ver>_openwrt-armv7.ipk` | OpenWrt, `armv7l` |
| `cattunnel_<ver>_openwrt-x86_64.ipk`, `cattunnel_<ver>_entware-x86_64.ipk` | OpenWrt or Entware on x86_64 |
| `cattunnel_<ver>_entware-<arch>.ipk` | Keenetic and ASUS Merlin with Entware; `<arch>` is `aarch64`, `armv7` or `mipsel` |
| `cattunnel-<ver>-r0_openwrt25-<arch>.apk` | OpenWrt 25.x (apk) |
| `luci-app-cattunnel_<ver>_openwrt-all.ipk` | LuCI pages for OpenWrt 23.05 and 24.10 |
| `luci-app-cattunnel-<ver>-r0_openwrt25.apk` | LuCI pages for OpenWrt 25.x |

The `Architecture: all` label of `.ipk` and `noarch` of `.apk` is for the package manager: the binaries inside are static and built for a specific CPU. Before unpacking, `preinst` checks the CPU, the platform, free space, memory and the kernel. After installation `postinst` runs `trusttunnel_client --version`, because apk 3 may carry on installing after `preinst` refuses.

For `.apk` the version is converted to the apk format: the suffix `-b1` becomes `_beta1-r0` and `-rc1` becomes `_rc1-r0`. The package contains `cattunnel`, `trusttunnel_client`, `age`, `age-keygen`, the licenses and the engine patches.

## One command (install.sh)

```
curl -fsSLO https://github.com/Cattunnel/cattunnel-router/releases/latest/download/install.sh && sh install.sh
```

The installer detects the system (OpenWrt with opkg, OpenWrt with apk, or Entware) and the CPU, then checks for Linux 3.2 or newer, 64 MB of memory or more, and free space on disk and in `/tmp`. Then it downloads the package and compares its SHA-256 with the hash built into `install.sh` itself.

```text
install.sh --> system and CPU --> checks (kernel, memory, space, /tmp, tun)
                                         |
              failed: nothing is installed, the reason is printed
                                         v
        download from a mirror --> verify SHA-256 --> save the old package
                                         v
          install --> does the engine start? --no--> roll back
                                         |yes
                                         v
                          install LuCI pages (OpenWrt)
```

Figure 1. What `install.sh` does.

On an update the old files and the package database are kept until replaced, and a package manager failure counts as an error and triggers a rollback. If a running service is updated with the kill switch on, a temporary block stays until the tunnel passes a check or the recovery time runs out. It limits the traffic of the selected `DEVICES`, or of the whole LAN when the list is empty. The backup needs extra space in `/tmp`.

```
sh install.sh --check          # only check
sh install.sh                  # install or update (plus LuCI if present)
sh install.sh --reinstall      # reinstall the same version
sh install.sh --no-luci        # without LuCI pages
sh install.sh --file /tmp/<package>   # offline (scp), the hash is still verified
sh install.sh --from /tmp/ct   # offline: all release files in a folder, hashes verified
```

## OpenWrt 23.05 / 24.10 (opkg) and 25.x (apk)

```
opkg update && opkg install curl kmod-tun
opkg install /tmp/cattunnel_<ver>_openwrt-<arch>.ipk
cattunnel import '<subscription link>'   # the device key is created automatically
cattunnel list                       # servers; * is the chosen one
cattunnel use <key>                  # choose a server from "cattunnel list"
/etc/init.d/cattunnel start
cattunnel test                       # "ok: internet through the tunnel works"
```

On OpenWrt without an external proxy, enable `tun` mode with `cattunnel set MODE tun && cattunnel firewall on && /etc/init.d/cattunnel restart`. `firewall on` creates the fw4 zone `cattunnel` for `tt0` with masquerading and forwarding from the LAN to the tunnel.

On OpenWrt 25.x use the `…_openwrt25-<arch>.apk` packages and `apk add --allow-untrusted /tmp/<package>.apk`. `install.sh` makes the update backup, and a direct package manager command does not.

## Keenetic (Entware)

You need the "OPKG" component and an installed Entware. If Entware is not found (no `/opt/bin/opkg`), the installer stops and says what to do.

```
opkg update && opkg install curl
opkg install /tmp/cattunnel_<ver>_entware-<arch>.ipk
cattunnel import '…' 'AGE-SECRET-KEY-1…' && cattunnel list
cattunnel set MODE tun                # the whole LAN into the tunnel; leave it for socks
/opt/etc/init.d/S99cattunnel start
```

Keenetic rebuilds iptables on network changes, so the hook `/opt/etc/ndm/netfilter.d/50-cattunnel.sh` restores the CatTunnel rules: masquerading and FORWARD for `tt0`, device marks, access to the web page and the temporary block of an unfinished update.

## ASUS Merlin (Entware)

On ASUS Merlin install the Entware package for the right CPU. To restore the rules after iptables is rebuilt, add `/opt/bin/cattunnel firewall on` to `/jffs/scripts/nat-start` and make the file executable. This hook restores the tunnel rules. The temporary block during an update was not tested separately on Merlin.

## Signature check

You can check the signature of `install.sh` on a PC: `openssl pkeyutl -verify -pubin -inkey cattunnel-release.pub.pem -rawin -in install.sh -sigfile <(base64 -d install.sh.sig)`. The public key is in `keys/cattunnel-release.pub.pem` and is part of every package.

If a binary does not fit the CPU, `postinst` leaves a `WRONG_ARCH` marker and `install.sh` installs the right package even when the version matches. A failed first install is removed, and an update restores the saved files.
