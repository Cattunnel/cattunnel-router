"""Exercise the real shell report with isolated firmware/files and adversarial secrets."""
import json
from pathlib import Path
import unittest
import test_device_key as harness
from test_device_key import BUNDLE, ROOT


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.DeviceKeyTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        harness.DeviceKeyTests.tearDownClass()

    def setUp(self):
        self.router = harness.DeviceKeyTests(methodName='runTest')
        self.router.setUp()
        self.addCleanup(self.router.doCleanups)

    def test_report_is_useful_and_never_exports_raw_secrets(self):
        r = self.router
        secrets = ['AGE-SECRET-KEY-1PRIVATE', 'client-password', 'private-client-name',
                   'aa:bb:cc:dd:ee:ff', 'https://sub.example/api/ct/private-token',
                   'private-server-name', '192.0.2.13', 'tt://PRIVATE']
        (r.etc / 'servers.bundle').write_bytes(BUNDLE + ('\n'.join(secrets)).encode())
        (r.etc / 'age.key').write_text(secrets[0])
        (r.etc / 'cattunnel.conf').write_text(
            "SUB_URL='https://sub.example/api/ct/private-token'\n"
            "DEVICES='aa:bb:cc:dd:ee:ff private-client-name'\n"
            "MODE='tun'\n")
        (r.run / 'engine.log').write_text('TLS error ' + ' '.join(secrets) + '\nDNS failed private-token\n')
        result = r.call('report')
        self.assertEqual(result.returncode, 0, result.stderr)
        for secret in secrets:
            self.assertNotIn(secret, result.stdout)
        for useful in ['problem report v1', 'Mode: tun', 'Subscription: configured',
                       'Server count: 1', 'TLS/handshake', 'DNS', 'Device selection: configured']:
            self.assertIn(useful, result.stdout)

    def test_report_works_before_subscription_is_added(self):
        (self.router.etc / 'cattunnel.conf').unlink()
        result = self.router.call('report')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Subscription: absent', result.stdout)
        self.assertIn('Server count: 0', result.stdout)

    def test_unknown_settings_are_not_echoed(self):
        (self.router.etc / 'cattunnel.conf').write_text("MODE='private-client-name'\nDNS='secret-password'\n")
        result = self.router.call('report')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('private-client-name', result.stdout)
        self.assertNotIn('secret-password', result.stdout)
        self.assertIn('Mode: unknown', result.stdout)

    def test_web_permissions_and_download_are_wired(self):
        acl = json.loads((ROOT / 'openwrt/luci-app-cattunnel/root/usr/share/rpcd/acl.d/luci-app-cattunnel.json').read_text())
        self.assertEqual(acl['luci-app-cattunnel']['read']['file']['/usr/bin/cattunnel report'], ['exec'])
        api = (ROOT / 'entware/opt/share/cattunnel/www/cgi-bin/api').read_text()
        self.assertIn('"report|"', api)
        ui = (ROOT / 'openwrt/luci-app-cattunnel/htdocs/luci-static/resources/view/cattunnel/diagnostics.js').read_text()
        self.assertIn("ct.run([ 'report' ])", ui)
        self.assertIn('link.download', ui)
        self.assertIn('URL.revokeObjectURL', ui)


if __name__ == '__main__':
    unittest.main()
