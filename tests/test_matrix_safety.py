"""Safety checks use boundary doubles and never contact Docker or host watchdog."""
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import router_matrix as matrix


def result(stdout=''):
    return subprocess.CompletedProcess([], 0, stdout, '')


class MatrixSafetyTests(unittest.TestCase):
    def test_result_cache_tracks_packaged_hooks_and_added_or_removed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            files = ['install.sh.in', 'build_packages.sh', 'tests/router_matrix.py',
                     'tests/fixtures/router_engine.c', 'common/cattunnel',
                     'openwrt/cattunnel/files/etc/init.d/cattunnel',
                     'entware/opt/etc/init.d/S99cattunnel',
                     'entware/opt/etc/ndm/netfilter.d/50-cattunnel.sh']
            for relative in files:
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original')
            original = matrix.matrix_source_hash(source)
            for relative in files:
                with self.subTest(file=relative):
                    path = source / relative
                    path.write_text('changed')
                    self.assertNotEqual(original, matrix.matrix_source_hash(source))
                    path.write_text('original')
            extra = source / 'common/new-helper'
            extra.write_text('new')
            self.assertNotEqual(original, matrix.matrix_source_hash(source))
            extra.unlink()
            self.assertEqual(original, matrix.matrix_source_hash(source))
            (source / files[-1]).unlink()
            self.assertNotEqual(original, matrix.matrix_source_hash(source))

    def inspect(self, privileged=False, devices=None):
        return result(json.dumps([{'HostConfig': {'Privileged': privileged, 'Devices': devices or []}}]))

    def test_privileged_inspect_refuses_before_docker_exec(self):
        with patch.object(matrix, 'run', return_value=self.inspect(True)) as run, patch.object(matrix, 'dex') as dex:
            with self.assertRaisesRegex(RuntimeError, 'Privileged must be false'):
                matrix.preflight(['unsafe'])
            run.assert_called_once_with(['docker', 'inspect', 'unsafe'])
            dex.assert_not_called()

    def test_watchdog_mapping_refused_on_either_side(self):
        for field in ('PathOnHost', 'PathInContainer'):
            with self.subTest(field=field), patch.object(matrix, 'run', return_value=self.inspect(devices=[{field: '/dev/watchdog0'}])):
                with self.assertRaisesRegex(RuntimeError, 'watchdog device mapping'):
                    matrix.preflight(['unsafe'])

    def test_watchdog_visible_inside_refused(self):
        with patch.object(matrix, 'run', return_value=self.inspect()), patch.object(matrix, 'dex', return_value=result('/dev/watchdog0\n')):
            with self.assertRaisesRegex(RuntimeError, 'watchdog visible inside'):
                matrix.preflight(['unsafe'])

    def test_all_inspections_precede_any_exec(self):
        with patch.object(matrix, 'run', side_effect=[self.inspect(), self.inspect(True)]), patch.object(matrix, 'dex') as dex:
            with self.assertRaises(RuntimeError):
                matrix.preflight(['safe', 'unsafe'])
            dex.assert_not_called()

    def test_safe_containers_pass(self):
        with patch.object(matrix, 'run', return_value=self.inspect()), patch.object(matrix, 'dex', return_value=result()):
            matrix.preflight(['safe'])

    def test_cleanup_checks_watchdog_last_even_on_failure(self):
        events = []
        lab = matrix.Matrix(None)
        def remove():
            events.append('remove')
            raise RuntimeError('cleanup failed')
        with patch.object(matrix, 'remove_containers', side_effect=remove), patch.object(matrix, 'check_watchdog', side_effect=lambda: events.append('watchdog')):
            with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
                lab.close(remove=True)
        self.assertEqual(events, ['remove', 'watchdog'])

    def test_active_or_unreadable_watchdog_is_failure(self):
        with patch.object(matrix, 'run', return_value=result('active\n')):
            with self.assertRaisesRegex(RuntimeError, 'DANGER'):
                matrix.check_watchdog()
        with patch.object(matrix, 'run', side_effect=RuntimeError('cannot read state')):
            with self.assertRaisesRegex(RuntimeError, 'DANGER: cannot read'):
                matrix.check_watchdog()

    def test_inactive_watchdog_passes(self):
        with patch.object(matrix, 'run', return_value=result('inactive\n')):
            matrix.check_watchdog()

    def test_cleanup_refuses_to_claim_success_if_container_remains(self):
        with patch.object(matrix, 'run', side_effect=[result(), result('container-id\n')]):
            with self.assertRaisesRegex(RuntimeError, 'still exists'):
                matrix.remove_containers()
