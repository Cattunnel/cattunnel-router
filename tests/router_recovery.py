"""Stand recovery checks with the real installer and container restarts.

Uses the isolated fixtures provisioned by router_matrix.py; no external hosts.
A container restart exercises service boot, not a host power loss.
"""
import argparse
import json
from pathlib import Path
import time

from router_matrix import Matrix, ROUTERS, dex, pid, preflight, run


def recovery(root):
    preflight()
    matrix = Matrix(root)
    matrix.safe = True
    rows = []
    directory = root / 'recovery'
    directory.mkdir(exist_ok=True)
    try:
        matrix.quiesce()
        matrix.start_control()
        for flavor, name in ROUTERS.items():
            matrix.configure_network(flavor, name)
            etc = matrix.etc(flavor)
            cli = matrix.ct(flavor)
            init = matrix.init(flavor)
            for scenario in ['stale-lock', 'dead-lock', 'sigkill', 'sigkill-expiry',
                             'boot-pending', 'boot-pending-lock', 'expired-pending']:
                dex(name, cli + ' stop --force', check=False)
                matrix.stop_engine(name)
                dex(name, f'rm -rf {etc}/upgrade.lock; rm -f {etc}/upgrade.pending {etc}/autostart.off')
                matrix.settings(flavor, name, 'tun', True)
                installed = matrix.install(flavor, name, '9.159.1', reinstall=True)
                (directory / f'{flavor}-{scenario}-prepare.log').write_text(installed.stdout + installed.stderr)
                if installed.returncode:
                    raise RuntimeError('recovery baseline install failed')
                dex(name, init + ' restart')
                matrix.probe(flavor, name)
                if scenario in ['stale-lock', 'dead-lock']:
                    stamp = '1' if scenario == 'stale-lock' else '$(date +%s)'
                    rundir = '/opt/var/run/cattunnel' if flavor == 'entware' else '/var/run/cattunnel'
                    owner = f'$(cat {rundir}/run.pid)' if scenario == 'stale-lock' else '99999999'
                    dex(name, f'mkdir -p {etc}/upgrade.lock; echo {owner} > {etc}/upgrade.lock/pid; echo {stamp} > {etc}/upgrade.lock/time')
                    result = matrix.install(flavor, name, '9.159.2', reinstall=True)
                    (directory / f'{flavor}-{scenario}.log').write_text(result.stdout + result.stderr)
                    if result.returncode:
                        raise RuntimeError(scenario + ' blocked next installer')
                    matrix.probe(flavor, name)
                elif scenario in ['sigkill', 'sigkill-expiry']:
                    # Pause only the lab copy immediately after the real snapshot.
                    ready = root / f'{name}-snapshot-ready'
                    ready.unlink(missing_ok=True)
                    paused = root / f'{name}-paused-install.sh'
                    source = (root / '9.159.2/install.sh').read_text()
                    needle = '\tupgrade_snapshot\n'
                    if source.count(needle) != 1:
                        raise RuntimeError('cannot locate unique installer snapshot call')
                    source = source.replace(needle, needle + f'\techo $$ > /lab/{ready.name}\n\twhile :; do sleep 1; done\n')
                    paused.write_text(source)
                    frozen = None
                    if scenario == 'sigkill-expiry':
                        # Model an old supervisor with no pending/TTL support.
                        rundir = '/opt/var/run/cattunnel' if flavor == 'entware' else '/var/run/cattunnel'
                        frozen = int(dex(name, f'cat {rundir}/run.pid').stdout)
                        dex(name, f'kill -STOP {frozen}')
                    try:
                        dex(name, f'sh /lab/{paused.name} --no-luci --from /lab/9.159.2 --reinstall > /lab/recovery/{flavor}-{scenario}.log 2>&1 &')
                        deadline = time.monotonic() + 20
                        while not ready.exists() and time.monotonic() < deadline:
                            time.sleep(.1)
                        if not ready.exists():
                            raise RuntimeError('installer did not reach snapshot')
                        installer_pid = int(ready.read_text())
                        dex(name, f'test -f {etc}/upgrade.pending && test -d {etc}/upgrade.lock && kill -9 {installer_pid}')
                        if frozen is not None:
                            # No CLI pending command: only the detached watch
                            # can expire this marker while the supervisor sleeps.
                            dex(name, f'touch -t 200001010000 {etc}/upgrade.pending')
                            deadline = time.monotonic() + 12
                            while dex(name, f'test -f {etc}/upgrade.pending', check=False).returncode == 0 and time.monotonic() < deadline:
                                time.sleep(.1)
                            dex(name, f'test ! -f {etc}/upgrade.pending')
                            if flavor == 'entware':
                                if 'CT_UP_' in matrix.count(flavor, name):
                                    raise RuntimeError('expiry left the independent iptables barrier')
                            elif dex(name, 'nft list table inet cattunnel_upgrade', check=False).returncode == 0:
                                raise RuntimeError('expiry left the independent nft barrier')
                            if not matrix.http_client('ct159-client'):
                                raise RuntimeError('expiry did not restore the healthy old tunnel')
                    finally:
                        if frozen is not None:
                            dex(name, f'kill -CONT {frozen}', check=False)
                    result = matrix.install(flavor, name, '9.159.2', reinstall=True)
                    (directory / f'{flavor}-after-{scenario}.log').write_text(result.stdout + result.stderr)
                    if result.returncode:
                        raise RuntimeError('killed installer blocked next install')
                    matrix.probe(flavor, name)
                elif scenario.startswith('boot-'):
                    dex(name, f'touch {etc}/upgrade.pending; {cli} hold')
                    if scenario.endswith('-lock'):
                        dex(name, f'mkdir -p {etc}/upgrade.lock; echo 99999999 > {etc}/upgrade.lock/pid; date +%s > {etc}/upgrade.lock/time')
                    matrix.stop_engine(name)
                    boot_ready = root / (name + '-boot-ready')
                    if flavor != 'entware':
                        # OpenWrt runs rc.local from S95done. Waiting for it
                        # prevents S20network starting AFTER our network stop.
                        boot_ready.unlink(missing_ok=True)
                        dex(name, f"printf '#!/bin/sh\\ntouch /lab/{boot_ready.name}\\n' > /etc/rc.local")
                    run(['docker', 'restart', name])
                    if flavor == 'entware':
                        time.sleep(2)
                    else:
                        deadline = time.monotonic() + 45
                        while not boot_ready.exists() and time.monotonic() < deadline:
                            time.sleep(.1)
                        if not boot_ready.exists():
                            raise RuntimeError('OpenWrt boot did not reach rc.local')
                    preflight()
                    run(['nsenter', '-t', pid(name), '-u', 'hostname', name])
                    if flavor != 'entware':
                        # netifd's boot reconciliation can otherwise delete the
                        # manually configured bridge after configure_network().
                        dex(name, '/etc/init.d/network stop; /etc/init.d/cron stop; /etc/init.d/dnsmasq stop', check=False)
                    for proc in matrix.processes.pop('http', []):
                        matrix.stop_process(proc)
                    matrix.configure_network(flavor, name)
                    dex(name, init + ' restart')
                    matrix.probe(flavor, name)
                else:
                    dex(name, f'touch {etc}/upgrade.pending; {cli} hold; touch -t 200001010000 {etc}/upgrade.pending')
                    dex(name, cli + ' pending', check=False)
                    dex(name, f'test ! -f {etc}/upgrade.pending')
                dex(name, cli + ' stop --force')
                matrix.stop_engine(name)
                if not matrix.http_client('ct159-client'):
                    raise RuntimeError('direct HTTP did not recover after ' + scenario)
                row = {'platform': flavor, 'scenario': scenario, 'pass': True}
                rows.append(row)
                (root / 'recovery-results.json').write_text(json.dumps(rows, indent=2))
                print(json.dumps(row), flush=True)
            for proc in matrix.processes.pop('http', []):
                matrix.stop_process(proc)
    finally:
        matrix.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    recovery(parser.parse_args().root)
