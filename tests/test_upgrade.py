"""Exercise update barriers and real filesystem rollback without touching host firewall."""
import os
import signal
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.upgrade-test-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.trace = self.base / 'trace'
        self.trace.touch()
        self.env = dict(os.environ, PATH=f'{self.bin}:/usr/bin:/bin', TRACE=str(self.trace))

    def executable(self, path, source):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\n' + source)
        path.chmod(0o755)

    def shell(self, source):
        return subprocess.run(['sh', '-eu', '-c', source], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_nft_barrier_is_one_inet_transaction_before_engine_stop(self):
        firmware = self.base / 'openwrt_release'
        firmware.touch()
        self.executable(self.bin / 'nft', '''echo "$*" >> "$TRACE"
case "$1" in list) exit 1 ;; -f) cat >> "$TRACE" ;; esac
''')
        helpers = (ROOT / 'common/upgrade.sh').read_text().replace('/etc/openwrt_release', str(firmware))
        result = self.shell(helpers + '\nguard_family() { command -v "$1" >/dev/null; }\nupgrade_guard on\necho STOP >> "$TRACE"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        trace = self.trace.read_text()
        self.assertIn('table inet cattunnel_upgrade', trace)
        self.assertIn('hook forward priority -310', trace)
        self.assertIn('hook prerouting priority -110', trace)
        self.assertLess(trace.index('counter drop'), trace.index('STOP'))

    def test_iptables_requires_both_families_and_stops_on_failure(self):
        for name in ('iptables', 'ip6tables'):
            self.executable(self.bin / name, '''echo "$(basename "$0") $*" >> "$TRACE"
case " $* " in *" -C "*) exit 1 ;; *" -L "*) exit 0 ;; esac
[ "$(basename "$0")" != ip6tables ]
''')
        helpers = (ROOT / 'common/upgrade.sh').read_text().replace('/etc/openwrt_release', str(self.base / 'absent'))
        result = self.shell(helpers + '\nguard_family() { command -v "$1" >/dev/null; }\nupgrade_guard on\necho STOP >> "$TRACE"\n')
        self.assertNotEqual(result.returncode, 0)
        trace = self.trace.read_text()
        self.assertIn('iptables -w -I FORWARD 1 -j CT_UP_F_A', trace)
        self.assertIn('iptables -w -t mangle -A CT_UP_P_A -j CATTUNNEL_DEV', trace)
        self.assertIn('ip6tables -w -t mangle -F CT_UP_F_A', trace)
        self.assertNotIn('STOP', trace)

    def test_selected_scope_resolves_names_and_never_widens_an_unknown_name(self):
        etc = self.base / 'etc'
        etc.mkdir()
        (etc / 'cattunnel.conf').write_text("DEVICES='AA:BB:CC:DD:EE:FF Phone* unknown'\n")
        helpers = (ROOT / 'common/upgrade.sh').read_text()
        result = self.shell(helpers + f'''\nguard_hosts() {{ echo '02:00:00:00:00:02 192.0.2.2 Phone_one -'; echo '02:00:00:00:00:03 192.0.2.3 other -'; }}
guard_scope '{etc}'
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['selected', '02:00:00:00:00:02', 'aa:bb:cc:dd:ee:ff'])
        (etc / 'cattunnel.conf').write_text("DEVICES='unknown'\n")
        result = self.shell(helpers + f"\nguard_hosts() {{ :; }}\nguard_scope '{etc}'\n")
        self.assertEqual(result.stdout.strip(), 'selected')

    def test_selected_nft_scope_only_drops_device_macs_or_device_mark(self):
        etc = self.base / 'etc'
        etc.mkdir()
        (etc / 'cattunnel.conf').write_text("DEVICES='02:00:00:00:00:02'\n")
        firmware = self.base / 'openwrt_release'
        firmware.touch()
        self.executable(self.bin / 'nft', '''case "$1" in list) exit 1 ;; -f) cat >> "$TRACE" ;; esac
''')
        helpers = (ROOT / 'common/upgrade.sh').read_text().replace('/etc/openwrt_release', str(firmware))
        result = self.shell(helpers + f"\nupgrade_guard on '{etc}'\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        rules = self.trace.read_text()
        self.assertIn('elements = { 02:00:00:00:00:02 }', rules)
        self.assertIn('meta mark 0x1801 jump blocked', rules)
        self.assertIn('ether saddr @macs jump blocked', rules)
        self.assertNotIn('\njump blocked\n', rules)

    def test_persistent_tun_barrier_survives_engine_exit_and_allows_tunnel_return(self):
        firmware = self.base / 'openwrt_release'
        firmware.touch()
        self.executable(self.bin / 'nft', '''echo "$*" >> "$TRACE"
case "$1" in list) exit 1 ;; -f) cat >> "$TRACE" ;; esac
''')
        helpers = (ROOT / 'common/upgrade.sh').read_text().replace('/etc/openwrt_release', str(firmware))
        result = self.shell(helpers + '\ntun_guard on tt0\necho ENGINE_EXIT >> "$TRACE"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        trace = self.trace.read_text()
        self.assertIn('table inet cattunnel_ks', trace)
        self.assertIn('oifname "tt0" accept', trace)
        self.assertIn('iifname "tt0" accept', trace)
        self.assertIn('counter drop', trace)
        self.assertNotIn('delete table', trace)

    def transaction(self, outcome, running=True, autostart_off=False, stale_lock=False, kill_installer=False, broken_rollback=False, stopping=False, prior_pending=False):
        target = self.base / 'opt'
        etc = target / 'etc/cattunnel'
        etc.mkdir(parents=True)
        conf = etc / 'cattunnel.conf'
        (etc / 'servers.bundle').write_text('saved subscription')
        run = target / 'var/run/cattunnel'
        run.mkdir(parents=True)
        if running:
            (run / 'run.pid').write_text(str(os.getpid()))
        if stopping:
            (run / 'stopping').touch()
        if prior_pending:
            (etc / 'upgrade.pending').write_text('previous-installer')
        if autostart_off:
            (etc / 'autostart.off').touch()
        if stale_lock:
            lock = etc / 'upgrade.lock'; lock.mkdir()
            (lock / 'pid').write_text('99999999')
            (lock / 'time').write_text(str(int(time.time())))
        conf.write_text("MODE='tun'\nDEVICES='phone'\nIDLE_STOP='600'\n")
        engine = target / 'libexec/cattunnel/trusttunnel_client'
        engine.parent.mkdir(parents=True)
        engine.write_text('old-engine')
        status = target / 'lib/opkg/status'
        status.parent.mkdir(parents=True)
        status.write_text('old-package-database')
        init = target / 'etc/init.d/S99cattunnel'
        self.executable(init, 'echo "service $*" >> "$TRACE"\n')
        cli = target / 'bin/cattunnel'
        self.executable(cli, 'echo "cli $*" >> "$TRACE"\nexit 0\n')
        extra = engine.parent / 'new-only-file'
        self.executable(self.bin / 'pm', f'printf "%s\\n" "{engine}" "{init}" "{cli}"\n[ ! -f "{extra}" ] || echo "{extra}"\n')
        work = self.base / 'work'
        work.mkdir()
        template = (ROOT / 'install.sh.in').read_text()
        functions = template[template.index('UPGRADE_ACTIVE=0\n'):template.index('[ "$FETCH" = curl ]')]
        functions = functions.replace('sleep 5', 'sleep 0.02')
        functions = functions.replace('/opt/etc/init.d/S99cattunnel', str(init))
        functions = functions.replace('/opt/bin/cattunnel', str(cli))
        source = f'''TARGET='{target}'
KIND=entware
PM=pm
TMPD='{work}'
fail() {{ echo "$*" >&2; exit 1; }}
warn() {{ echo "$*" >&2; }}
upgrade_guard() {{ echo "guard $*" >> "$TRACE"; }}
tun_guard() {{ echo "persistent $*" >> "$TRACE"; }}
{(ROOT / 'common/upgrade.sh').read_text().split('guard_hosts()')[0]}
{functions}
upgrade_snapshot
printf new-engine > '{engine}'
printf new-database > '{status}'
printf new-file > '{extra}'
install_exit {outcome}
'''
        if broken_rollback:
            source = 'tar() { if [ "$1" = -xzf ]; then return 9; else command tar "$@"; fi; }\n' + source
        if kill_installer:
            ready = self.base / 'installer-ready'
            paused = source.replace('upgrade_snapshot\nprintf', f"upgrade_snapshot\ntouch '{ready}'\nsleep 60\nprintf")
            proc = subprocess.Popen(['sh', '-eu', '-c', paused], env=self.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    start_new_session=True)
            try:
                deadline = time.monotonic() + 3
                while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists(), 'installer never reached snapshot')
                self.assertTrue((etc / 'upgrade.pending').exists())
            finally:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate(timeout=3)
            self.assertEqual(proc.returncode, -signal.SIGKILL)
            self.assertTrue((etc / 'upgrade.lock').exists())
        result = self.shell(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            recovered = not (etc / 'upgrade.pending').exists()
            if recovered:
                break
            time.sleep(.01)
        self.assertFalse((etc / 'upgrade.lock').exists())
        self.assertFalse((etc / 'upgrade.pending').exists())
        self.assertEqual(work.exists(), broken_rollback)
        if outcome and not broken_rollback:
            self.assertFalse(extra.exists())
        return engine, status, self.trace.read_text()

    def test_failed_update_restores_files_database_and_restarts_old_service(self):
        engine, status, trace = self.transaction(1)
        self.assertEqual(engine.read_text(), 'old-engine')
        self.assertEqual(status.read_text(), 'old-package-database')
        self.assertIn('service stop', trace)
        self.assertIn('service start', trace)
        self.assertNotIn('cli set IDLE_STOP', trace)
        self.assertIn('persistent off tt0', trace)
        self.assertLess(trace.index('guard on'), trace.index('service stop'))
        self.assertLess(trace.index('cli test'), trace.index('guard off'))

    def test_legacy_rollback_after_interrupted_install_keeps_current_recovery_token(self):
        engine, status, trace = self.transaction(1, prior_pending=True)
        self.assertEqual(engine.read_text(), 'old-engine')
        self.assertEqual(status.read_text(), 'old-package-database')
        self.assertIn('cli test', trace)
        self.assertIn('guard off', trace)

    def test_success_keeps_new_package_and_releases_only_after_probe(self):
        engine, status, trace = self.transaction(0)
        self.assertEqual(engine.read_text(), 'new-engine')
        self.assertEqual(status.read_text(), 'new-database')
        self.assertNotIn('service stop', trace)
        self.assertLess(trace.index('cli test'), trace.index('guard off'))

    def test_installer_rejects_nonzero_pm_even_when_new_engine_runs(self):
        import hashlib
        target = self.base / 'opt'
        etc = target / 'etc/cattunnel'
        etc.mkdir(parents=True)
        (etc / 'cattunnel.conf').write_text("MODE='socks'\n")
        (etc / 'servers.bundle').write_text('subscription')
        engine = target / 'libexec/cattunnel/trusttunnel_client'
        self.executable(engine, 'echo old-engine\n')
        old_engine = engine.read_bytes()
        cli = target / 'bin/cattunnel'
        self.executable(cli, 'echo "cli $*" >> "$TRACE"\nexit 0\n')
        init = target / 'etc/init.d/S99cattunnel'
        self.executable(init, 'echo "service $*" >> "$TRACE"\n')
        status = target / 'lib/opkg/status'
        status.parent.mkdir(parents=True)
        status.write_text('old-status')
        self.executable(target / 'bin/opkg', f'''case "$1" in
print-architecture) echo 'arch x86_64 10' ;;
list-installed) echo 'cattunnel - 1.0'; echo 'curl - 1.0' ;;
files) printf '%s\\n' '{engine}' '{init}' '{cli}' ;;
install) printf '#!/bin/sh\\necho new-engine\\n' > '{engine}'; echo new-status > '{status}'; exit 5 ;;
*) exit 2 ;;
esac
''')
        for name in ('iptables', 'ip6tables'):
            self.executable(self.bin / name, 'case " $* " in *" -C "*) exit 1 ;; esac\nexit 0\n')
        self.executable(self.bin / 'uname', 'case "$1" in -m) echo x86_64 ;; -r) echo 6.1 ;; esac\n')
        self.executable(self.bin / 'id', 'echo 0\n')
        packages = self.base / 'packages'
        packages.mkdir()
        package = packages / 'cattunnel-test.ipk'
        package.write_bytes(b'test-package')
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        tmpdir = self.base / 'tmp'
        tmpdir.mkdir()
        script = (ROOT / 'install.sh.in').read_text()
        script = script.replace('@UPGRADE_HELPERS@', (ROOT / 'common/upgrade.sh').read_text())
        script = script.replace('@VER@', '2.0').replace('@MIRRORS@', '')
        script = script.replace('@PKGS@', f'entware x86_64 {package.name} {digest} 1')
        script = script.replace('/opt', str(target)).replace('/tmp', str(tmpdir))
        script = script.replace('/etc/openwrt_release', str(self.base / 'absent-firmware'))
        installer = self.base / 'install.sh'
        installer.write_text(script)
        result = subprocess.run(['sh', str(installer), '--from', str(packages)], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('код 5', result.stderr)
        self.assertEqual(engine.read_bytes(), old_engine)
        self.assertEqual(status.read_text(), 'old-status')
        deadline = time.monotonic() + 2
        while (etc / 'upgrade.pending').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse((etc / 'upgrade.pending').exists())

    def test_package_builder_embeds_helper_and_preserves_cleanup_during_reinstall(self):
        import tarfile
        binaries = self.base / 'binaries'
        for name in ('trusttunnel_client', 'age', 'age-keygen'):
            self.executable(binaries / f'{name}-x86_64', 'echo fixture\n')
        license_file = self.base / 'tt-build/TTC-clean/LICENSE'
        license_file.parent.mkdir(parents=True)
        license_file.write_text('fixture license')
        out = self.base / 'packages'
        builder = (ROOT / 'build_packages.sh').read_text()
        builder = builder.replace('ROOT=$(cd "$(dirname "$0")" && pwd)', f"ROOT='{ROOT}'")
        builder = builder.replace('OUT=$ROOT/build', f"OUT='{out}'")
        script = self.base / 'build.sh'
        script.write_text(builder)
        env = dict(self.env, HOME=str(self.base), ROUTER_BIN=str(binaries),
                   AGE_LICENSE=str(license_file), APK=str(self.base / 'no-apk'),
                   UPDATE_SIGNING_KEY=str(self.base / 'no-signing-key'))
        result = subprocess.run(['bash', str(script), '0.0.0-test', 'x86_64'],
                                env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installer = (out / 'install.sh').read_text()
        self.assertNotIn('@UPGRADE_HELPERS@', installer)
        self.assertIn('upgrade_guard() {', installer)
        for flavor in ('openwrt', 'entware'):
            package = out / f'cattunnel_0.0.0-test_{flavor}-x86_64.ipk'
            with tarfile.open(package) as archive:
                with tarfile.open(fileobj=archive.extractfile('./data.tar.gz')) as data:
                    prefix = './usr' if flavor == 'openwrt' else './opt/usr'
                    self.assertIn(prefix + '/share/cattunnel/upgrade.sh', data.getnames())
                    self.assertIn(prefix + '/share/cattunnel/exchange.awk', data.getnames())
                with tarfile.open(fileobj=archive.extractfile('./control.tar.gz')) as control:
                    hook = control.extractfile('./prerm').read().decode()
                    self.assertIn('CATTUNNEL_INSTALL_UPGRADE', hook)
                    import re
                    cli = self.bin / 'hook-cli'
                    self.executable(cli, 'echo "$*" >> "$TRACE"\n[ "${HOOK_FAIL:-0}" != 1 ]\n')
                    isolated = re.sub(r'/(?:opt/)?bin/cattunnel|/usr/bin/cattunnel|/etc/init.d/cattunnel',
                                      str(cli), hook)
                    helper = self.bin/'hook-upgrade.sh'
                    helper.write_text('upgrade_guard() { echo "guard $*" >> "$TRACE"; }\n')
                    isolated = isolated.replace('/opt/usr/share/cattunnel/upgrade.sh', str(helper)).replace('/usr/share/cattunnel/upgrade.sh', str(helper))
                    isolated = isolated.replace('/etc/openwrt_release', str(self.base / 'absent-firmware'))
                    isolated = isolated.replace('/opt/etc/cattunnel/upgrade.pending', str(self.base / 'pending'))
                    isolated = isolated.replace('/etc/cattunnel/upgrade.pending', str(self.base / 'pending'))
                    isolated = isolated.replace('/opt/var/run/cattunnel/stopping', str(self.base/'hook-stopping')).replace('/var/run/cattunnel/stopping', str(self.base/'hook-stopping'))
                    for argument, in_installer, keep, stopped in [('upgrade', False, 1, False), ('remove', False, 1, False), ('remove', True, 1, False), ('remove', True, 0, False), ('upgrade', False, 0, False), ('upgrade', True, 1, True)]:
                        self.trace.write_text('')
                        (self.base/'pending').touch()
                        marker=self.base/'hook-stopping'
                        if stopped: marker.touch()
                        else: marker.unlink(missing_ok=True)
                        check = self.shell(f'CATTUNNEL_INSTALL_UPGRADE={int(in_installer)}; CATTUNNEL_INSTALL_KEEP_RULES={keep}; export CATTUNNEL_INSTALL_UPGRADE CATTUNNEL_INSTALL_KEEP_RULES\nset -- {argument}\n' + isolated)
                        self.assertEqual(check.returncode, 0, check.stderr)
                        trace = self.trace.read_text()
                        if (argument == 'upgrade' or in_installer) and keep and not stopped:
                            self.assertIn('stop --keep-rules', trace)
                            self.assertNotIn('cleanup', trace)
                            self.assertNotIn('guard off', trace)
                        else:
                            self.assertIn('stop --force\n', trace)
                            self.assertIn('guard off', trace)
                            if argument == 'remove' and not in_installer:
                                self.assertIn('cleanup', trace)
                    helper.write_text('upgrade_guard() { echo "guard $*" >> "$TRACE"; }\nupgrade_install_context() { echo 1; }\n')
                    (self.base/'hook-stopping').unlink(missing_ok=True)
                    self.trace.write_text('')
                    check = self.shell('unset CATTUNNEL_INSTALL_UPGRADE CATTUNNEL_INSTALL_KEEP_RULES\nset -- remove\n' + isolated)
                    self.assertEqual(check.returncode, 0, check.stderr)
                    self.assertIn('stop --keep-rules', self.trace.read_text())
                    self.assertNotIn('stop --force', self.trace.read_text())
                    helper.write_text('upgrade_guard() { echo "guard $*" >> "$TRACE"; }\n')
                    self.trace.write_text('')
                    check = self.shell('HOOK_FAIL=1; CATTUNNEL_INSTALL_KEEP_RULES=0; export HOOK_FAIL CATTUNNEL_INSTALL_KEEP_RULES\nset -- remove\n' + isolated)
                    self.assertEqual(check.returncode, 0, check.stderr)
                    self.assertIn('guard off', self.trace.read_text())
                    settings_dir = self.base/('postinst-'+flavor)
                    settings_dir.mkdir()
                    (settings_dir/'servers.bundle').write_text('subscription fixture')
                    fake_init = self.bin/'hook-init'
                    fake_engine = self.bin/'hook-engine'
                    self.executable(fake_init, 'echo "service $*" >> "$TRACE"\n')
                    self.executable(fake_engine, 'exit 0\n')
                    postinst = control.extractfile('./postinst').read().decode()
                    postinst = postinst.replace('/opt/etc/init.d/S99cattunnel', str(fake_init)).replace('/etc/init.d/cattunnel', str(fake_init))
                    postinst = postinst.replace('/opt/etc/cattunnel', str(settings_dir)).replace('/etc/cattunnel', str(settings_dir))
                    postinst = re.sub(r'/(?:opt|usr)/libexec/cattunnel/trusttunnel_client', str(fake_engine), postinst)
                    postinst = re.sub(r'/opt/bin/cattunnel|/usr/bin/cattunnel', str(cli), postinst)
                    postinst = postinst.replace('/opt/var/run/cattunnel/stopping', str(self.base/'post-stopping')).replace('/var/run/cattunnel/stopping', str(self.base/'post-stopping'))
                    for keep, stopped in [(0, False), (1, False), (1, True)]:
                        marker=self.base/'post-stopping'
                        if stopped: marker.touch()
                        else: marker.unlink(missing_ok=True)
                        self.trace.write_text('')
                        check = self.shell(f'CATTUNNEL_INSTALL_KEEP_RULES={keep}; export CATTUNNEL_INSTALL_KEEP_RULES\n' + postinst)
                        self.assertEqual(check.returncode, 0, check.stderr)
                        if keep and not stopped:
                            self.assertIn('service restart', self.trace.read_text())
                        else:
                            self.assertNotIn('service restart', self.trace.read_text())
                    for name in ('preinst', 'postinst', 'prerm'):
                        check = subprocess.run(['sh', '-n'], input=control.extractfile('./' + name).read(),
                                               capture_output=True)
                        self.assertEqual(check.returncode, 0, check.stderr)

    def test_new_supervisor_protocol_prevents_early_installer_release(self):
        etc=self.base/'etc'; etc.mkdir()
        (etc/'upgrade.pending').touch()
        (etc/'upgrade.lock').mkdir()
        (etc/'upgrade.lock/pid').write_text('$$')
        work=self.base/'work';work.mkdir()
        cli=self.bin/'cattunnel'
        self.executable(cli, 'echo "$*" >> "$TRACE"\n[ "$1" != upgrade-protocol ] || echo 1\n')
        template=(ROOT/'install.sh.in').read_text()
        functions=template[template.index('UPGRADE_ACTIVE=0\n'):template.index('[ "$FETCH" = curl ]')]
        functions=functions.replace('/opt/bin/cattunnel',str(cli))
        functions=functions.replace('sleep 5', 'sleep 0.1').replace('ug_attempt" -lt 60', 'ug_attempt" -lt 4')
        source=f'''KIND=entware; TARGET='{self.base}'; TMPD='{work}'
warn() {{ :; }}
upgrade_guard() {{ echo "guard $*" >> "$TRACE"; }}
{functions}
UPGRADE_ACTIVE=2
UPGRADE_GUARDED=1
UPGRADE_PENDING_TOKEN=
echo $$ > '{etc}/upgrade.lock/pid'
UPGRADE_ETC='{etc}'
UPGRADE_RUN='{self.base}'
install_exit 0
'''
        result=self.shell(source)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((etc/'upgrade.pending').exists())
        self.assertFalse((etc/'upgrade.lock').exists())
        # A new supervisor owns release during the initial observation window.
        time.sleep(.05)
        self.assertNotIn('guard off',self.trace.read_text())
        self.assertNotIn('test\n',self.trace.read_text())
        deadline = time.monotonic() + 8
        while (etc/'upgrade.pending').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse((etc/'upgrade.pending').exists())
        self.assertIn('guard off', self.trace.read_text())

    def lifecycle(self, commands):
        source = (ROOT / 'common/cattunnel').read_text()
        functions = source[source.index('rules_pending() {'):source.index('stop_engine() {')]
        dispatch = source[source.index('\t# These internal commands'):source.index('\tstatus)', source.index('\t# These internal commands'))]
        # Keep the real command dispatch but replace the external platform/engine operations.
        dispatch = dispatch[:dispatch.index('\trestart)')]
        dispatch = dispatch.replace('/etc/openwrt_release', str(self.base / 'absent'))
        etc = self.base / 'etc'
        run = self.base / 'run'
        etc.mkdir(); run.mkdir()
        bundle = etc / 'servers.bundle'
        bundle.write_text('saved subscription')
        script = f'''ETC='{etc}'; RUN='{run}'; BUNDLE='{bundle}'; KILLSWITCH=on
upgrade_guard() {{ echo "guard $*" >> "$TRACE"; }}
dns_apply() {{ echo "dns $*" >> "$TRACE"; }}
devices_apply() {{ echo "devices $*" >> "$TRACE"; }}
firewall() {{ echo "firewall $*" >> "$TRACE"; }}
stop_all() {{ echo stop-engine >> "$TRACE"; }}
die() {{ echo "$*" >&2; exit 1; }}
{(ROOT / 'common/upgrade.sh').read_text().split('guard_hosts()')[0]}
{functions}
command_stop() {{
 case "$1" in
{dispatch}
 esac
}}
{commands}
'''
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.trace.read_text(), etc, run

    def test_user_stop_returns_direct_internet_and_cancels_restart_barrier(self):
        trace, etc, run = self.lifecycle('hold_rules\ncommand_stop stop\n')
        self.assertIn('guard on', trace)
        for event in ('stop-engine', 'dns off', 'devices off', 'firewall off', 'guard off'):
            self.assertIn(event, trace)
        self.assertFalse((run / 'restart.pending').exists())
        self.assertTrue((run / 'stopping').exists())
        self.assertTrue((etc / 'servers.bundle').exists())

    def test_internal_stop_keeps_rules_and_sets_restart_marker(self):
        trace, _, run = self.lifecycle('command_stop stop --keep-rules\n')
        self.assertLess(trace.index('guard on'), trace.index('stop-engine'))
        self.assertNotIn(' off', trace)
        self.assertTrue((run / 'restart.pending').exists())

    def test_upgrade_marker_keeps_rules_even_for_plain_stop(self):
        trace, etc, _ = self.lifecycle('touch "$ETC/upgrade.pending"\ncommand_stop stop\n')
        self.assertIn('guard on', trace)
        self.assertIn('stop-engine', trace)
        self.assertNotIn(' off', trace)
        self.assertTrue((etc / 'upgrade.pending').exists())

    def test_openwrt_stop_restart_and_package_flag_have_distinct_paths(self):
        source = (ROOT / 'openwrt/cattunnel/files/etc/init.d/cattunnel').read_text()
        cli = self.bin / 'cattunnel'
        self.executable(cli, 'echo "cli $*" >> "$TRACE"\n[ "$1" != pending ]\n')
        pending = self.base / 'upgrade.pending'
        source = source.replace('/usr/bin/cattunnel', str(cli))
        source = source.replace('/etc/cattunnel/upgrade.pending', str(pending))
        source = source.replace('killall ', 'fake_killall ').replace('sleep 1', ':').replace('ip link delete tt0', 'fake_ip')
        fake = 'fake_killall() { :; }; fake_ip() { :; }\n'
        for action, flag, protected in [('stop', '0', False), ('restart', '0', True), ('stop', '1', True)]:
            with self.subTest(action=action, keep_rules=flag):
                self.trace.write_text('')
                result = self.shell(fake + source + f'\naction={action}; CATTUNNEL_KEEP_RULES={flag}\nstop_service\nservice_stopped\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                trace = self.trace.read_text()
                if protected:
                    self.assertIn('cli hold', trace)
                    self.assertNotIn('cli cleanup', trace)
                else:
                    self.assertIn('cli prepare-stop', trace)
                    self.assertIn('cli cleanup', trace)

    def test_on_demand_is_disabled_while_update_is_pending(self):
        source = (ROOT / 'common/cattunnel').read_text()
        function = "\n".join(line for line in source.splitlines() if line.startswith(('rules_pending()', 'on_demand()')))
        pending = self.base / 'upgrade.pending'
        result = self.shell(f"ETC='{self.base}'; RUN='{self.base}'; MODE=tun; DEVICES=phone; IDLE_STOP=600\n" + (ROOT / 'common/upgrade.sh').read_text().split('guard_hosts()')[0] + function +
                            f'\non_demand\ntouch "{pending}"\nif on_demand; then exit 1; fi\n')
        self.assertEqual(result.returncode, 0, result.stderr)


    def test_stale_lock_is_reclaimed_by_installer(self):
        engine, _, trace = self.transaction(0, stale_lock=True)
        self.assertEqual(engine.read_text(), 'new-engine')
        self.assertIn('guard on', trace)

    def test_zombie_installer_does_not_own_a_live_lock(self):
        etc = self.base / 'zombie-lock'
        lock = etc / 'upgrade.lock'
        lock.mkdir(parents=True)
        child = subprocess.Popen(['sleep', '60'])
        try:
            os.kill(child.pid, signal.SIGKILL)
            deadline = time.monotonic() + 2
            status = Path(f'/proc/{child.pid}/status')
            while 'State:\tZ' not in status.read_text():
                self.assertLess(time.monotonic(), deadline, 'child did not become a zombie')
                time.sleep(.01)
            # Do not reap before checking: this is the kill -0 false positive.
            os.kill(child.pid, 0)
            (lock / 'pid').write_text(str(child.pid))
            (lock / 'time').write_text(str(int(time.time())))
            helper = (ROOT / 'common/upgrade.sh').read_text()
            result = self.shell(helper + f"\nif upgrade_lock_live '{etc}'; then exit 5; fi\n")
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            child.wait()

    def test_stopped_service_and_autostart_off_do_not_block_lan(self):
        for running, disabled in [(False, False), (True, True)]:
            # Each transaction needs its own filesystem fixture.
            with self.subTest(running=running, disabled=disabled):
                self.setUp()
                _, _, trace = self.transaction(0, running=running, autostart_off=disabled)
                self.assertNotIn('guard on', trace)

    def test_force_stop_releases_pending_update_and_keeps_subscription(self):
        trace, etc, run = self.lifecycle('touch "$ETC/upgrade.pending"\ncommand_stop stop --force\n')
        self.assertIn('guard off', trace)
        self.assertIn('devices off', trace)
        self.assertTrue((run / 'stopping').exists())
        self.assertFalse((etc / 'upgrade.pending').exists())
        self.assertTrue((etc / 'servers.bundle').exists())

    def test_installer_respects_user_stop_even_with_a_stale_live_pid(self):
        _, _, trace = self.transaction(0, running=True, stopping=True)
        self.assertNotIn('guard on', trace)

    def test_stop_all_removes_pid_left_by_a_supervisor_without_its_term_trap(self):
        run = self.base / 'run'
        run.mkdir()
        (run / 'run.pid').write_text('99999999')
        self.executable(self.bin / 'pgrep', 'exit 1\n')
        source = (ROOT / 'common/cattunnel').read_text()
        body = source[source.index('stop_all() {'):source.index('# Пакет не для этого процессора.')]
        result = self.shell(f'''RUN='{run}'
PIDF='{run}/cattunnel.pid'
ENGINE=/absent-fixture-engine
TUN_DEV=absent-fixture-tun
run_pids() {{ :; }}
engine_running() {{ return 1; }}
{body}
stop_all
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((run / 'run.pid').exists())

    def test_pending_ttl_expires_even_with_a_live_lock(self):
        etc = self.base / 'etc'; etc.mkdir()
        pending = etc / 'upgrade.pending'; pending.touch()
        os.utime(pending, (time.time()-901, time.time()-901))
        lock = etc / 'upgrade.lock'; lock.mkdir()
        (lock/'pid').write_text(str(os.getpid()))
        (lock/'time').write_text(str(int(time.time())))
        helper = (ROOT / 'common/upgrade.sh').read_text().split('guard_hosts()')[0]
        result = self.shell(helper + f'''
upgrade_guard() {{ echo "guard $*" >> "$TRACE"; }}
upgrade_lock_live '{etc}'
if upgrade_pending_live '{etc}'; then exit 5; fi
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(pending.exists())
        self.assertIn('guard off', self.trace.read_text())

    def test_explicit_install_context_requires_a_live_lock(self):
        lock = self.base / 'upgrade.lock'; lock.mkdir()
        (lock / 'pid').write_text(str(os.getpid()))
        (lock / 'time').write_text(str(int(time.time())))
        (lock / 'context').write_text('install')
        (lock / 'keep-rules').write_text('0')
        helper = (ROOT / 'common/upgrade.sh').read_text().split('guard_hosts()')[0]
        result = self.shell(helper + f'\nupgrade_install_context "{self.base}"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '0')
        unrelated = subprocess.Popen(['sleep', '30'])
        try:
            (lock / 'pid').write_text(str(unrelated.pid))
            result = self.shell(helper + f'\nupgrade_install_context "{self.base}"\n')
            self.assertNotEqual(result.returncode, 0)
        finally:
            unrelated.terminate(); unrelated.wait()
        (lock / 'pid').write_text('99999999')
        result = self.shell(helper + f'\nupgrade_install_context "{self.base}"\n')
        self.assertNotEqual(result.returncode, 0)

    def test_pending_ttl_without_busybox_stat(self):
        self.executable(self.bin / 'stat', 'exit 127\n')
        etc = self.base / 'etc'; etc.mkdir()
        pending = etc / 'upgrade.pending'; pending.touch()
        helper = (ROOT / 'common/upgrade.sh').read_text().split('guard_hosts()')[0]
        source = helper + f'\nupgrade_guard() {{ echo "guard $*" >> "$TRACE"; }}\nupgrade_pending_live "{etc}"\n'
        fresh = self.shell(source)
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertTrue(pending.exists())
        os.utime(pending, (time.time()-901, time.time()-901))
        expired = self.shell(source)
        self.assertNotEqual(expired.returncode, 0)
        self.assertFalse(pending.exists())
        self.assertIn('guard off', self.trace.read_text())

    def test_dead_or_old_lock_and_rebooted_lock_do_not_stall_supervisor(self):
        etc = self.base / 'etc'; etc.mkdir()
        lock = etc / 'upgrade.lock'; lock.mkdir()
        helper = (ROOT / 'common/upgrade.sh').read_text().split('guard_hosts()')[0]
        for pid, timestamp, boot in [('99999999', time.time(), None), (str(os.getpid()), time.time()-901, None), (str(os.getpid()), time.time(), 'previous-boot'), ('not-a-pid', time.time(), None), (str(os.getpid()), 'bad:timestamp', None)]:
            with self.subTest(pid=pid, boot=boot):
                (lock/'pid').write_text(pid)
                (lock/'time').write_text(str(int(timestamp)) if not isinstance(timestamp, str) else timestamp)
                if boot: (lock/'boot').write_text(boot)
                else: (lock/'boot').unlink(missing_ok=True)
                result = self.shell(helper + f"\nif upgrade_lock_live '{etc}'; then exit 5; fi\n")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_ipv4_only_entware_works_without_wait_option_or_ipv6(self):
        self.executable(self.bin/'iptables', '''echo "$*" >> "$TRACE"
case " $* " in *" -w "*|*" -C "*) exit 1 ;; esac
exit 0
''')
        helper = (ROOT / 'common/upgrade.sh').read_text().replace('/etc/openwrt_release', str(self.base/'absent'))
        result = self.shell(helper + '\nguard_family() { [ "$1" = iptables ]; }\nupgrade_guard on\ntun_guard on tt0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        trace = self.trace.read_text()
        self.assertEqual(trace.count('-w -L -n'), 1)
        self.assertIn('-I FORWARD 1 -j CT_UP_F_A', trace)
        self.assertIn('-I FORWARD 1 -j CATTUNNEL_KS', trace)


    def test_old_supervisor_cannot_release_a_fresh_restart_barrier(self):
        trace, _, run = self.lifecycle('''
echo old > "$RUN/restart.pending"
RESTART_TOKEN=$(pending_token "$RUN/restart.pending")
echo fresh > "$RUN/restart.pending"
release_pending_after_probe
[ -f "$RUN/restart.pending" ]
RESTART_TOKEN=$(pending_token "$RUN/restart.pending")
release_pending_after_probe
''')
        self.assertEqual(trace.count('guard off'), 1)
        self.assertFalse((run/'restart.pending').exists())


    def test_sigkill_after_real_installer_snapshot_allows_next_install(self):
        engine, _, trace = self.transaction(0, kill_installer=True)
        self.assertEqual(engine.read_text(), 'new-engine')
        self.assertGreaterEqual(trace.count('guard on'), 2)


    def test_broken_rollback_releases_barrier_and_retains_archive(self):
        engine, _, trace = self.transaction(1, broken_rollback=True)
        self.assertEqual(engine.read_text(), 'new-engine')
        self.assertIn('guard off', trace)
        self.assertTrue((self.base/'work/previous.tar.gz').exists())


    def test_reboot_pending_releases_after_probe_without_live_install_lock(self):
        for with_lock in (False, True):
            with self.subTest(with_lock=with_lock):
                self.setUp()
                commands = '''
touch "$ETC/upgrade.pending"
UPGRADE_TOKEN=$(pending_token "$ETC/upgrade.pending")
'''
                if with_lock:
                    commands += '''
mkdir "$ETC/upgrade.lock"
echo $$ > "$ETC/upgrade.lock/pid"
date +%s > "$ETC/upgrade.lock/time"
echo previous-boot > "$ETC/upgrade.lock/boot"
'''
                trace, etc, _ = self.lifecycle(commands + 'release_pending_after_probe\n')
                self.assertIn('guard off', trace)
                self.assertFalse((etc/'upgrade.pending').exists())

    def test_plain_stop_ignores_expired_pending(self):
        trace, etc, run = self.lifecycle('''
touch "$ETC/upgrade.pending"
touch -t 200001010000 "$ETC/upgrade.pending"
command_stop stop
''')
        self.assertIn('guard off', trace)
        self.assertIn('devices off', trace)
        self.assertIn('dns off', trace)
        self.assertFalse((etc/'upgrade.pending').exists())
        self.assertTrue((run/'stopping').exists())


    def test_recovery_does_not_own_a_following_installers_pending(self):
        etc = self.base/'etc'; etc.mkdir()
        (etc/'upgrade.pending').write_text('next-install')
        template = (ROOT/'install.sh.in').read_text()
        functions = template[template.index('UPGRADE_ACTIVE=0\n'):template.index('[ "$FETCH" = curl ]')]
        result = self.shell(functions + f'''
UPGRADE_ETC='{etc}'
UPGRADE_GUARDED=1
UPGRADE_PENDING_TOKEN=previous-install
if upgrade_owns_pending; then exit 5; fi
[ "$(cat "$UPGRADE_ETC/upgrade.pending")" = next-install ]
''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_expiry_watch_survives_sigkill_before_old_release_can_read_pending(self):
        for replace_token in [False, True]:
            with self.subTest(replace_token=replace_token):
                etc = self.base / ('expiry-' + str(replace_token))
                etc.mkdir()
                pending = etc / 'upgrade.pending'
                pending.write_text('installer-owner')
                ready = etc / 'ready'
                template = (ROOT / 'install.sh.in').read_text()
                functions = template[template.index('UPGRADE_ACTIVE=0\n'):template.index('[ "$FETCH" = curl ]')]
                functions = functions.replace('sleep 5', 'sleep 0.02')
                helper = (ROOT / 'common/upgrade.sh').read_text().split('guard_hosts()')[0]
                source = f'''{helper}
{functions}
UPGRADE_ETC='{etc}'
UPGRADE_GUARDED=1
UPGRADE_PENDING_TOKEN=installer-owner
upgrade_guard() {{ echo "expired {replace_token}" >> "$TRACE"; }}
upgrade_start_expiry_watch
touch '{ready}'
exec sleep 60
'''
                proc = subprocess.Popen(['sh', '-eu', '-c', source], env=self.env,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True)
                try:
                    deadline = time.monotonic() + 2
                    while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(ready.exists(), 'expiry watch did not start')
                    os.kill(proc.pid, signal.SIGKILL)
                    proc.communicate(timeout=2)
                    if replace_token:
                        pending.write_text('next-installer')
                    os.utime(pending, (1, 1))
                    if replace_token:
                        time.sleep(.1)
                        self.assertEqual(pending.read_text(), 'next-installer')
                        self.assertNotIn('expired True', self.trace.read_text())
                    else:
                        deadline = time.monotonic() + 2
                        while pending.exists() and time.monotonic() < deadline:
                            time.sleep(.01)
                        self.assertFalse(pending.exists())
                        self.assertIn('expired False', self.trace.read_text())
                finally:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()


if __name__ == '__main__':
    unittest.main()
