"""Run the real router shell and curl; select real age via CATTUNNEL_TEST_AGE_DIR.

Breaks caught: missing device headers/identity, rotating or losing a key,
clobbering a working bundle on failure, and disabling legacy decryption.
Without CATTUNNEL_TEST_AGE_DIR, age executables are boundary doubles. Run: python3 -m unittest discover -s tests -v
"""
import http.server
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEST_SHELL = os.environ.get('CATTUNNEL_TEST_SHELL', 'sh')
REAL_AGE_DIR = os.environ.get('CATTUNNEL_TEST_AGE_DIR', '')
PUBLIC = 'age1' + 'q' * 58
SECRET = 'AGE-SECRET-KEY-1DEVICE'
LEGACY = 'AGE-SECRET-KEY-1LEGACY'
BUNDLE = b'# cattunnel-router 1\n@server de R0VS auto=1\n[endpoint]\nanti_dpi = true\n@end\n'


class DeviceKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []
        cls.responses = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                cls.requests.append((self.path, dict(self.headers)))
                status, body = cls.responses.get(self.path, (404, b''))
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        for port in range(21000, 21100):
            try:
                cls.server = http.server.HTTPServer(('127.0.0.1', port), Handler)
                break
            except OSError:
                continue
        else:
            raise RuntimeError('No available test port in 21000–21099')
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.device-test-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.etc = self.base / 'etc'
        self.lib = self.base / 'lib'
        self.run = self.base / 'run'
        for d in (self.etc, self.lib, self.run):
            d.mkdir()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.executable(self.bin / 'logger', '#!/bin/sh\nexit 0\n')
        # Double understands only the age CLI contract used by the router.
        self.executable(self.lib / 'age-keygen', f'''#!/bin/sh
case "${{1:-}}" in
'') printf '%s\\n' '# public key: {PUBLIC}' '{SECRET}' ;;
-o) [ ! -e "$2" ] || exit 1; printf '%s\\n' '# public key: {PUBLIC}' '{SECRET}' > "$2" ;;
-y) grep -qx '{SECRET}' "$2" || exit 1; echo '{PUBLIC}' ;;
*) exit 2 ;;
esac
''')
        self.executable(self.lib / 'age', f'''#!/bin/sh
identities=''
while [ "$#" -gt 0 ]; do
 case "$1" in
 -d) shift ;;
 -i) value=$(cat "$2"); case "$value" in *{SECRET}*|*{LEGACY}*) ;; *) exit 1 ;; esac; identities="$identities $value"; shift 2 ;;
 -o) out=$2; shift 2 ;;
 *) input=$1; shift ;;
 esac
done
want=$(sed -n '2p' "$input")
case "$want:$identities" in
 device:*{SECRET}*|legacy:*{LEGACY}*) sed '1,2d' "$input" > "$out" ;;
 *) exit 1 ;;
esac
''')
        share = self.base / 'share'
        share.mkdir()
        (share / 'VERSION').write_text('1.5.7\n')
        self.legacy = LEGACY
        if REAL_AGE_DIR:
            for name in ('age', 'age-keygen'):
                (self.lib / name).unlink()
                (self.lib / name).symlink_to(Path(REAL_AGE_DIR).resolve() / name)
            generated = subprocess.run([str(self.lib / 'age-keygen')],
                                       capture_output=True, text=True, check=True).stdout
            self.legacy = next(line for line in generated.splitlines() if line.startswith('AGE-SECRET-KEY-'))
        self.script = self.base / 'cattunnel'
        source = (ROOT / 'common/cattunnel').read_text()
        # Firmware paths are isolated without exposing test switches in production.
        source = source.replace('/opt/usr/share/cattunnel', str(share))
        source = source.replace('/usr/share/cattunnel', str(share))
        for path in ('/etc/openwrt_release', '/etc/ndm', '/tmp/sysinfo/model',
                     '/proc/device-tree/model', '/sys/firmware/devicetree/base/model',
                     '/proc/cpuinfo', '/etc/version'):
            source = source.replace(path, str(self.base / path.lstrip('/')))
        self.script.write_text(source)
        self.env = dict(os.environ, CATTUNNEL_ETC=str(self.etc),
                        CATTUNNEL_LIB=str(self.lib), CATTUNNEL_RUN=str(self.run),
                        PATH=str(self.bin) + ':/usr/bin:/bin')
        self.requests.clear()
        self.responses.clear()
        self.responses['/sub?format=router'] = (200, BUNDLE)
        self.settings(f'{self.url}/sub')

    @staticmethod
    def executable(path, text):
        path.write_text(text)
        path.chmod(0o755)

    def settings(self, url):
        (self.etc / 'cattunnel.conf').write_text(f"SUB_URL='{url}'\nSERVER='de'\n")

    def call(self, *args):
        return subprocess.run([TEST_SHELL, str(self.script), *args], env=self.env,
                              input='', text=True, capture_output=True, timeout=10)

    def updated(self, *args):
        result = self.call(*(args or ('update',)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.etc / 'servers.bundle').read_bytes(), BUNDLE)
        return result

    def public_key(self):
        if not REAL_AGE_DIR:
            return PUBLIC
        return subprocess.check_output([str(self.lib / 'age-keygen'), '-y',
                                        str(self.etc / 'device.key')], text=True).strip()

    def encrypted(self, identity):
        if not REAL_AGE_DIR:
            return b'age-encryption.org/v1\n' + identity.encode() + b'\n' + BUNDLE
        if identity == 'device':
            result = self.functions('device_identity')
            self.assertEqual(result.returncode, 0, result.stderr)
            keyfile = self.etc / 'device.key'
        else:
            keyfile = self.base / 'recipient.key'
            if identity == 'legacy':
                keyfile.write_text(self.legacy + '\n')
            else:
                generated = subprocess.run([str(self.lib / 'age-keygen')],
                                           capture_output=True, check=True).stdout
                keyfile.write_bytes(generated)
        recipient = subprocess.check_output([str(self.lib / 'age-keygen'), '-y', str(keyfile)],
                                            text=True).strip()
        return subprocess.run([str(self.lib / 'age'), '-r', recipient], input=BUNDLE,
                              capture_output=True, check=True).stdout

    def test_update_sends_device_headers_and_private_identity_persists(self):
        self.updated()
        headers = {k.lower(): v for k, v in self.requests[-1][1].items()}
        self.assertEqual(headers.get('x-device-key'), self.public_key())
        self.assertEqual(headers.get('x-app-version'), 'cattunnel-router/1.5.7')
        self.assertEqual(headers.get('x-device-os'), 'entware')
        self.assertTrue(headers.get('x-device-model'))
        self.assertRegex(headers.get('x-hwid', ''), r'^[0-9a-f]{32}$')
        self.assertTrue(headers.get('x-ver-os'))
        hwid = headers['x-hwid']
        key = self.etc / 'device.key'
        before = key.read_bytes(), key.stat().st_ino
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.updated()
        self.assertEqual((key.read_bytes(), key.stat().st_ino), before)
        self.assertEqual({k.lower(): v for k, v in self.requests[-1][1].items()}['x-hwid'], hwid)

    def test_hwid_is_random_per_install_and_private(self):
        self.updated()
        identity = self.etc / 'device.id'
        before = identity.read_text()
        self.assertEqual(identity.stat().st_mode & 0o777, 0o600)
        identity.unlink()
        self.updated()
        self.assertNotEqual(identity.read_text(), before)
        self.assertRegex(identity.read_text(), r'^[0-9a-f]{32}$')

    def test_corrupt_hwid_is_not_rotated_or_sent(self):
        # x-hwid is optional: a broken device.id must not stop the subscription update.
        (self.etc / 'device.id').write_text('broken\n')
        self.updated()
        self.assertEqual((self.etc / 'device.id').read_text(), 'broken\n')
        self.assertTrue(self.requests)
        self.assertNotIn('broken', ''.join(str(r) for r in self.requests))

    def test_import_creates_device_identity_and_keeps_legacy_key(self):
        self.updated('import', f'{self.url}/sub', self.legacy)
        self.assertTrue((self.etc / 'device.key').is_file())
        self.assertEqual((self.etc / 'age.key').read_text(), self.legacy + '\n')

    def test_device_encrypted_response_without_legacy_identity(self):
        self.responses['/sub?format=router'] = (200, self.encrypted('device'))
        self.updated()

    def test_legacy_encrypted_response_after_migration(self):
        (self.etc / 'age.key').write_text(self.legacy + '\n')
        self.responses['/sub?format=router'] = (200, self.encrypted('legacy'))
        self.updated()
        self.assertEqual((self.etc / 'age.key').read_text(), self.legacy + '\n')
        self.assertTrue((self.etc / 'device.key').is_file())

    def test_failure_preserves_bundle_and_device_identity(self):
        self.updated()
        self.assertTrue((self.etc / 'device.key').is_file(), 'device identity was not created')
        key = (self.etc / 'device.key').read_bytes()
        for status, body in ((403, b'pending'), (403, b'limit'), (403, b'revoked'),
                             (404, b''), (200, b'garbage'),
                             (200, self.encrypted('unknown'))):
            with self.subTest(status=status, body=body[:25]):
                self.responses['/sub?format=router'] = status, body
                self.assertNotEqual(self.call('update').returncode, 0)
                self.assertEqual((self.etc / 'servers.bundle').read_bytes(), BUNDLE)
                self.assertEqual((self.etc / 'device.key').read_bytes(), key)

    def test_mirrors_receive_same_identity(self):
        self.settings(f'{self.url}/bad | {self.url}/sub')
        self.updated()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual([dict((k.lower(), v) for k, v in h.items()).get('x-device-key')
                          for _, h in self.requests], [self.public_key(), self.public_key()])

    def test_saved_mirror_receives_identity(self):
        self.settings(f'{self.url}/bad')
        (self.etc / 'servers.bundle').write_bytes(BUNDLE + f'#mirrors {self.url}/sub?format=router\n'.encode())
        self.updated()
        self.assertEqual(len(self.requests), 2)
        headers = {k.lower(): v for k, v in self.requests[-1][1].items()}
        self.assertEqual(headers.get('x-device-key'), self.public_key())

    def test_corrupt_existing_identity_is_never_rotated(self):
        (self.etc / 'device.key').write_text('broken\n')
        (self.etc / 'servers.bundle').write_bytes(BUNDLE)
        self.assertNotEqual(self.call('update').returncode, 0)
        self.assertEqual((self.etc / 'device.key').read_text(), 'broken\n')
        self.assertEqual((self.etc / 'servers.bundle').read_bytes(), BUNDLE)
        self.assertEqual(self.requests, [])

    def test_keygen_failure_does_not_publish_partial_key(self):
        (self.lib / 'age-keygen').unlink()
        self.executable(self.lib / 'age-keygen', '#!/bin/sh\necho partial\nexit 1\n')
        (self.etc / 'servers.bundle').write_bytes(BUNDLE)
        self.assertNotEqual(self.call('update').returncode, 0)
        self.assertFalse((self.etc / 'device.key').exists())
        self.assertEqual(list(self.etc.glob('device.key.*')), [])
        self.assertEqual(self.requests, [])

    def test_firmware_metadata_is_single_header(self):
        model = self.base / 'tmp/sysinfo/model'
        model.parent.mkdir(parents=True)
        model.write_bytes(b'Test Router\r\nx-injected: bad\x00')
        release = self.base / 'etc/openwrt_release'
        release.write_text("DISTRIB_RELEASE='24.10.0'\n")
        self.updated()
        headers = {k.lower(): v for k, v in self.requests[-1][1].items()}
        self.assertEqual(headers.get('x-device-os'), 'openwrt')
        self.assertIn('Test Router', headers.get('x-device-model', ''))
        self.assertNotIn('x-injected', headers)
        self.assertEqual(headers.get('x-ver-os'), '24.10.0')

    def test_keenetic_metadata(self):
        (self.base / 'etc/ndm').mkdir()
        (self.base / 'etc/version').write_text('4.3.2\n')
        self.updated()
        headers = {k.lower(): v for k, v in self.requests[-1][1].items()}
        self.assertEqual(headers.get('x-device-os'), 'keenetic')
        self.assertEqual(headers.get('x-ver-os'), '4.3.2')

    def test_valid_device_response_ignores_damaged_legacy_key(self):
        (self.etc / 'age.key').write_text('damaged legacy identity\n')
        self.responses['/sub?format=router'] = (200, self.encrypted('device'))
        self.updated()

    def test_missing_keygen_preserves_existing_subscription(self):
        (self.lib / 'age-keygen').unlink()
        (self.etc / 'servers.bundle').write_bytes(BUNDLE)
        self.assertNotEqual(self.call('update').returncode, 0)
        self.assertEqual((self.etc / 'servers.bundle').read_bytes(), BUNDLE)
        self.assertEqual(self.requests, [])

    def functions(self, commands):
        source = self.script.read_text().split('# Пакет не для этого процессора.')[0]
        library = self.base / 'functions.sh'
        library.write_text(source + '\n' + commands + '\n')
        return subprocess.run([TEST_SHELL, str(library)], env=self.env, text=True,
                              capture_output=True, timeout=10)

    def test_auto_dpi_selection_and_explicit_override(self):
        (self.etc / 'servers.bundle').write_bytes(BUNDLE)
        result = self.functions("""
is_auto de || exit 11
OVR_DPI=off
if is_auto de; then exit 12; fi
OVR_DPI=auto
is_auto de || exit 13
local_dns_unusable() { return 1; }
write_toml de 2
cat "$TOML"
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('anti_dpi = true\n', result.stdout)
        self.assertIn('anti_dpi_mode = 2\n', result.stdout)

    def test_wan_dns_failure_uses_ip_fallback(self):
        self.executable(self.bin / 'ip', '#!/bin/sh\necho "default via 192.0.2.1 dev eth0"\n')
        self.executable(self.bin / 'nslookup', '#!/bin/sh\nexit 1\n')
        self.executable(self.bin / 'ping', '#!/bin/sh\n[ "$5" = 1.1.1.1 ]\n')
        result = self.functions('wan_dns() { echo 192.0.2.1; }; wan_ok')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wan_tunnel_only_default_is_rejected(self):
        self.executable(self.bin / 'ip', '#!/bin/sh\necho "default dev tt0"\n')
        self.executable(self.bin / 'nslookup', '#!/bin/sh\nexit 0\n')
        self.executable(self.bin / 'ping', '#!/bin/sh\nexit 0\n')
        result = self.functions('wan_dns() { echo 192.0.2.1; }; wan_ok')
        self.assertNotEqual(result.returncode, 0)

    @unittest.skipUnless(REAL_AGE_DIR or (shutil.which('age') and shutil.which('age-keygen')),
                         'real age and age-keygen are not installed')
    def test_real_age_device_and_legacy_roundtrip(self):
        for name in ('age', 'age-keygen'):
            (self.lib / name).unlink()
            (self.lib / name).symlink_to((Path(REAL_AGE_DIR).resolve() / name) if REAL_AGE_DIR else shutil.which(name))
        self.updated()
        recipient = subprocess.check_output(
            [str(self.lib / 'age-keygen'), '-y', str(self.etc / 'device.key')], text=True).strip()
        encrypted = subprocess.run([str(self.lib / 'age'), '-r', recipient],
                                   input=BUNDLE, capture_output=True, check=True).stdout
        self.responses['/sub?format=router'] = (200, encrypted)
        self.updated()
        identity = subprocess.run([str(self.lib / 'age-keygen')], capture_output=True, check=True).stdout
        (self.etc / 'age.key').write_bytes(identity)
        recipient = subprocess.check_output(
            [str(self.lib / 'age-keygen'), '-y', str(self.etc / 'age.key')], text=True).strip()
        encrypted = subprocess.run([str(self.lib / 'age'), '-r', recipient],
                                   input=BUNDLE, capture_output=True, check=True).stdout
        self.responses['/sub?format=router'] = (200, encrypted)
        self.updated()

    def test_package_rejects_missing_keygen(self):
        for name in ('age-x86_64', 'trusttunnel_client-x86_64'):
            self.executable(self.lib / name, '#!/bin/sh\nexit 0\n')
        result = subprocess.run(['bash', str(ROOT / 'build_packages.sh'), '1.5.7', 'x86_64'],
                                env=dict(self.env, ROUTER_BIN=str(self.lib), AGE_LICENSE='/dev/null'),
                                text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('age-keygen-x86_64', result.stderr)


if __name__ == '__main__':
    unittest.main()
