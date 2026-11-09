"""Capture real router-engine ClientHello against a local address in the lab netns.

Run in a dedicated network namespace with a dummy uplink and no physical
network connection. This observes ClientHello and warnings, not a successful VPN handshake.
"""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import threading
import time


def capture(root, arch):
    emulators = {'aarch64': 'qemu-aarch64', 'armv7': 'qemu-arm',
                 'mipsel': 'qemu-mipsel', 'mips': 'qemu-mips'}
    destination = root / 'tls'
    destination.mkdir(exist_ok=True)
    config = destination / (arch + '.toml')
    config.write_text('''loglevel = "debug"
vpn_mode = "general"
killswitch_enabled = false
[endpoint]
hostname = "local.invalid"
addresses = ["192.0.2.1:19443"]
has_ipv6 = false
username = "fixture"
password = "fixture"
client_random = ""
client_random_auth_key = "''' + '01' * 32 + '''"
skip_verification = true
dns_upstreams = ["127.0.0.1:19553"]
upstream_protocol = "http2"
tls_profile = "chrome"
anti_dpi = false
[listener.socks]
address = "127.0.0.1:19080"
''')
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('192.0.2.1', 19443))
    server.listen()
    server.settimeout(20)
    received = []

    def accept():
        try:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(10)
                received.append(conn.recv(65535))
                time.sleep(1)
        except OSError:
            pass

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    pcap = destination / (arch + '.pcap')
    with (destination / (arch + '-capture.log')).open('wb') as capture_log:
        recorder = subprocess.Popen(['tcpdump', '-i', 'any', '-U', '-w', str(pcap), 'tcp port 19443'], stdout=capture_log, stderr=capture_log)
        time.sleep(.5)
        with (destination / (arch + '.log')).open('wb') as logfile:
            engine = subprocess.Popen([emulators[arch], str(root / ('trusttunnel_client-' + arch)), '--config', str(config)], stdout=logfile, stderr=logfile)
            try:
                thread.join(15)
            finally:
                engine.terminate()
                try:
                    engine.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    engine.kill()
                    engine.wait()
                server.close()
        time.sleep(.3)
        recorder.terminate()
        recorder.wait(timeout=5)
    if not received or not received[0].startswith(b'\x16\x03'):
        raise RuntimeError(arch + ': no TLS ClientHello; inspect engine log')
    (destination / (arch + '-record.bin')).write_bytes(received[0])
    output = subprocess.run(['tshark', '-r', str(pcap), '-d', 'tcp.port==19443,tls', '-Y', 'tls.handshake.type == 1', '-T', 'fields', '-e', 'tls.handshake.ja4', '-e', 'tls.handshake.ja4_r', '-e', 'tls.handshake.sig_hash_alg'], capture_output=True, text=True, check=True)
    fields = output.stdout.strip().splitlines()[0].split('\t')
    ja4 = fields[0]
    log = (destination / (arch + '.log')).read_text(errors='replace')
    warning = 'SSL_set_custom_client_random is unavailable' in log
    mips = arch in ['mipsel', 'mips']
    if warning != mips:
        raise RuntimeError(arch + ': unexpected auth-key warning state')
    if not mips and ja4.endswith('d8a2da3f94cd'):
        raise RuntimeError(arch + ': unchanged obsolete JA4 signature')
    row = {'arch': arch, 'ja4': ja4, 'ja4_r': fields[1],
           'signature_algorithms': fields[2], 'auth_key_unavailable_warning': warning,
           'pass': True}
    (destination / (arch + '.json')).write_text(json.dumps(row, indent=2))
    print(json.dumps(row), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('arch', choices=['aarch64', 'armv7', 'mipsel', 'mips'])
    args = parser.parse_args()
    capture(args.root, args.arch)
