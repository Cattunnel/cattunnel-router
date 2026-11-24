Русский: [CONNECTION.ru.md](CONNECTION.ru.md)

# How the connection works

Briefly, step by step: from the core to the server. The router edition uses the same core as the CatTunnel app. The settings of each step are described in [settings.en.md](../docs/settings.en.md), and in LuCI and on the web page they are under "Settings".

```text
router: core --> TLS (ClientHello, SNI) --> anti-DPI splits the packet --> server
                                                                              |
 the subscription sets method, fingerprint, string, masking, QUIC <-----------+
```

Figure 1. The connection steps.

## 1. The core

- The connection is built by the TrustTunnel core, the `trusttunnel_client` program in the package. In CatTunnel it is built with changes: censorship bypass techniques, a custom bypass string, size masking and clear failure reasons.
- The tunnel is an ordinary secure HTTPS connection (HTTP/2 over TLS or HTTP/3 over QUIC) to the server. The traffic of the router or of the chosen devices goes inside it.

## 2. The handshake (TLS)

- The connection starts with the ClientHello, the first packet, which carries the server name (SNI) in plain text. This is what the provider's filter (TSPU) reads.
- The TLS fingerprint says which application this handshake looks like. The router offers `chrome`, `firefox`, `safari` and `okhttp`. The subscription usually sets it, and there is no need to change it.

## 3. Anti-DPI

- It changes only how the ClientHello goes onto the network: the packet stays whole for the server, while the filter sees it cut or out of order. HTTP/2 only.
- The basic method cuts the packet into two pieces with a pause.
- Methods 1, 2, 3 come from ByeDPI: an "urgent" byte that the server drops, and a piece with TTL 1 that is lost on the way and then arrives again.
- "Auto" tries methods 1, 2, 3 in turn, 15 seconds each, and remembers the one that worked for this server. The remembered method goes first next time.
- The custom string works as in ByeDPI: parts `-s`, `-o`, `-d` with a position, for example `-o1+s -d3+s`. The subscription or `OVR_DESYNC` sets it.

## 4. Size masking

- The first frames of a connection get random bytes added, so the sizes of the tunnel's first requests do not repeat. It is part of the HTTP/2 standard, and the server needs no setup.
- It is turned on by a frame count: `OVR_PADDING` from 1 to 64, set by the subscription or in the expert settings. Off by default.
- Turn off QUIC (`OVR_QUIC on`): apps behind the router cannot use UDP to port 443, which is QUIC, what YouTube and Chrome run on. They fall back to plain TCP at once. It helps compare speed and see whether QUIC gets in the way.

## 5. Connecting and retries

- The watchdog checks the internet through the tunnel every 30 seconds. If the chosen server does not answer for 2 minutes (4 checks in a row), the router moves to the next subscription server and tries to come back after 30 minutes.
- If the router itself loses internet, servers are not rotated, because they are not the cause.
- The core keeps 2-4 TLS connections to the server and pauses 2-6 seconds between handshakes, so there is no burst at start.

## 6. The server

- Nothing needs to be set up on the server: all the techniques work with a standard TrustTunnel server.
- The key (address, login, password) comes from the subscription. A subscription can set the bypass technique, the fingerprint, the custom string, size masking and QUIC off by itself. The router then takes them from there unless you override them.
