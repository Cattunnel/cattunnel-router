"""Root-only isolated Docker/netns packet checks; no Internet endpoints are used.

Production shell scripts and package managers are exercised with a deliberately
small test engine. socat provides a real TUN/UDP path to a local namespace;
this verifies packet containment and lifecycle, not TrustTunnel interoperability.
"""
import argparse
import contextlib
import hashlib
import http.server
import io
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import signal
import socket
import socketserver
import struct
import subprocess
import sys
import tarfile
import threading
import time

ROUTERS = {'ow24': 'ct159-ow24', 'ow25': 'ct159-ow25', 'entware': 'ct159-entware'}
TARGET = '198.51.100.159'
PORT = 18080
MAC1 = '02:00:00:00:59:02'
MAC2 = '02:00:00:00:59:03'


def run(args, check=True, timeout=40, **kwargs):
    p = subprocess.run([str(x) for x in args], capture_output=True, text=True,
                       timeout=timeout, **kwargs)
    if check and p.returncode:
        raise RuntimeError(f'{shlex.join(map(str,args))}: {p.stdout} {p.stderr}')
    return p


CONTAINERS = (*ROUTERS.values(), 'ct159-client', 'ct159-outside', 'ct159-exit')
WATCHDOG_STATE = '/sys/class/watchdog/watchdog0/state'


def matrix_source_hash(source):
    """Include packaged init scripts/hooks when deciding whether rows are reusable."""
    files = [source / relative for relative in
             ['install.sh.in', 'build_packages.sh', 'tests/router_matrix.py',
              'tests/fixtures/router_engine.c']]
    for directory in ['common', 'openwrt', 'entware']:
        files.extend(path for path in (source / directory).rglob('*') if path.is_file())
    digest = hashlib.sha256()
    for path in sorted(files):
        content = path.read_bytes()
        digest.update(path.relative_to(source).as_posix().encode() + b'\0')
        digest.update(str(len(content)).encode() + b'\0' + content)
    return digest.hexdigest()


def inspect_safety(name):
    """Fail closed before any namespace, firewall, service or build operation."""
    info = json.loads(run(['docker', 'inspect', name]).stdout)
    if len(info) != 1:
        raise RuntimeError(f'{name}: docker inspect did not return one container')
    config = info[0].get('HostConfig', {})
    if config.get('Privileged') is not False:
        raise RuntimeError(f'{name}: unsafe container: HostConfig.Privileged must be false')
    for device in config.get('Devices') or []:
        for field in ('PathOnHost', 'PathInContainer'):
            if 'watchdog' in device.get(field, ''):
                raise RuntimeError(f'{name}: unsafe watchdog device mapping: {device[field]}')


def preflight(names=CONTAINERS):
    # Inspect every container first, before executing even the ls probe inside one.
    for name in names:
        inspect_safety(name)
    for name in names:
        found = dex(name, 'for d in /dev/watchdog*; do [ ! -e "$d" ] && [ ! -L "$d" ] || printf "%s\\n" "$d"; done')
        if found.stdout.strip():
            raise RuntimeError(f'{name}: unsafe watchdog visible inside container: {found.stdout.strip()}')


def check_watchdog():
    try:
        state = run(['cat', WATCHDOG_STATE]).stdout.strip()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'DANGER: cannot read host watchdog state: {exc}') from exc
    if state != 'inactive':
        raise RuntimeError(f'DANGER: host watchdog state is {state!r}, expected inactive')
    print('watchdog: inactive', flush=True)


def remove_containers():
    for name in CONTAINERS:
        run(['docker', 'rm', '-f', name], check=False)
        remaining = run(['docker', 'ps', '-aq', '--filter', f'name=^/{name}$']).stdout.strip()
        if remaining:
            raise RuntimeError(f'Cleanup failed: container {name} still exists')


def pid(name):
    return int(run(['docker', 'inspect', '-f', '{{.State.Pid}}', name]).stdout)


def net(name, *args, **kw):
    return run(['nsenter', '-t', pid(name), '-n', *args], **kw)


def dex(name, script, check=True, timeout=40):
    return run(['docker', 'exec', '-e', 'PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin',
                name, '/bin/sh', '-c', script], check=check, timeout=timeout)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/subscription?format=router'):
            body = b'# cattunnel-router 1\n@server lab TGFib3JhdG9yeQ auto=0\n[endpoint]\nhostname = "local.invalid"\naddresses = ["198.19.159.2:443"]\nusername = "fixture"\npassword = "fixture"\n@end\n'
            self.send_response(200); self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(204); self.end_headers()

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size < 4096: raise ValueError('body length')
            data = json.loads(self.rfile.read(size))
            if self.path != '/api/ct/exchange': status = 404
            elif not re.fullmatch('age1[0-9a-z]{58}', data.get('device_key', '')): status = 400
            else: status = {'valid-code': 200, 'expired-code': 410, 'bad-code': 400}.get(data.get('code'), 404)
        except (ValueError, TypeError):
            status = 400
        reply = {'subscription': f'http://{self.headers["Host"]}/subscription'} if status == 200 else {'error': 'fixture error'}
        self.send_response(status); self.end_headers()
        self.wfile.write(json.dumps(reply).encode())

    def log_message(self, *args):
        pass


def serve_http():
    http.server.ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


def serve_http6():
    class Server(http.server.ThreadingHTTPServer):
        address_family=socket.AF_INET6
        def server_bind(self):
            self.socket.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
            super().server_bind()
    Server(('::',PORT),Handler).serve_forever()


class Socks(socketserver.BaseRequestHandler):
    def handle(self):
        def read(n):
            data = b''
            while len(data) < n:
                part = self.request.recv(n-len(data))
                if not part: raise EOFError()
                data += part
            return data
        try:
            ver, count = read(2); read(count)
            self.request.sendall(b'\x05\x00')
            ver, cmd, reserved, typ = read(4)
            if typ == 1: host = socket.inet_ntoa(read(4))
            elif typ == 3: host = read(read(1)[0]).decode()
            else: return
            port = struct.unpack('!H', read(2))[0]
            if host != TARGET or port != PORT: return
            peer = socket.socket()
            peer.bind(('198.18.159.1', 0)); peer.settimeout(3)
            peer.connect((host, port))
            self.request.sendall(b'\x05\x00\x00\x01'+b'\x00'*6)
            import select
            while True:
                ready, _, _ = select.select([peer, self.request], [], [], 3)
                if not ready: break
                for src in ready:
                    data = src.recv(65536)
                    if not data: return
                    (peer if src is self.request else self.request).sendall(data)
        except (OSError, EOFError) as exc:
            print(repr(exc),file=sys.stderr,flush=True)


def serve_socks():
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    Server(('0.0.0.0', 1080), Socks).serve_forever()


class Matrix:
    def __init__(self, root):
        self.root = root
        self.processes = {}
        self.all_processes = []
        self.rows = []
        self.control = None
        self.safe = False
        self.active_router = None
        self.lock = threading.Lock()
        self.events = []

    def quiesce(self):
        # A supervisor left by an interrupted run must not attach to the next
        # controller and replace another router's shared endpoint TUN device.
        for flavor, name in ROUTERS.items():
            dex(name, self.ct(flavor) + ' stop --force', check=False)

    def spawn_net(self, name, *cmd, logfile):
        if cmd[0]=='tcpdump': cmd=(cmd[0],'--immediate-mode',*cmd[1:])
        log = open(logfile, 'ab')
        p = subprocess.Popen(['nsenter', '-t', str(pid(name)), '-n', *map(str,cmd)],
                             stdout=log, stderr=log, start_new_session=True)
        log.close()
        self.all_processes.append(p)
        return p

    def stop_process(self, proc):
        if proc and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL); proc.wait()

    def stop_engine(self, name):
        with self.lock:
            self.events.append({'event':'stop','router':name,'time':time.time()})
            for proc in self.processes.pop(name, []): self.stop_process(proc)
            net(name, 'ip', 'link', 'del', 'tt0', check=False)
            net('ct159-exit', 'ip', 'link', 'del', 'ttsrv', check=False)

    def start_engine(self, name):
        self.stop_engine(name)
        state = json.loads((self.root / f'{name}.json').read_text())
        time.sleep(state.get('delay', .4))
        server = self.spawn_net('ct159-exit', 'socat',
            'UDP-LISTEN:45555,reuseaddr',
            'TUN:198.18.159.2/30,tun-name=ttsrv,iff-up,iff-no-pi',
            logfile=self.root/'socat-server.log')
        client = self.spawn_net(name, 'socat',
            'TUN:198.18.159.1/30,tun-name=tt0,iff-up,iff-no-pi',
            'UDP:198.19.159.2:45555', logfile=self.root/'socat-client.log')
        with self.lock: self.processes[name] = [server, client]
        deadline = time.monotonic()+4
        while time.monotonic() < deadline:
            if net(name, 'ip', 'link', 'show', 'tt0', check=False).returncode == 0: break
            time.sleep(.03)
        net(name, 'ip', 'link', 'set', 'tt0', 'mtu', '1350')
        if name != ROUTERS.get('entware'): dex(name,'/etc/init.d/firewall reload')
        net(name, 'ip', 'route', 'replace', TARGET+'/32', 'dev', 'tt0', 'table', '219')
        net(name, 'ip', 'rule', 'add', 'from', '198.18.159.1', 'lookup', '219', 'pref', '1800', check=False)
        if state['mode'] == 'tun' and not state['selected']:
            net(name, 'ip', 'route', 'replace', TARGET+'/32', 'dev', 'tt0')
        proxy = self.spawn_net(name, 'python3', self.root/'src/tests/router_matrix.py', '--socks',
                               logfile=self.root/'socks.log')
        with self.lock:
            self.processes[name].append(proxy)
            self.events.append({'event':'ready','router':name,'time':time.time()})
        return 'OK'

    def start_control(self):
        matrix = self
        class Control(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    action, name = self.rfile.readline().decode().strip().split()
                    if name not in ROUTERS.values(): raise ValueError(name)
                    if action == 'start': matrix.start_engine(name)
                    elif action == 'stop': matrix.stop_engine(name)
                    else: raise ValueError(action)
                    self.wfile.write(b'OK\n')
                except Exception as e:
                    with open(matrix.root/'controller-errors.log','a') as f: f.write(repr(e)+'\n')
                    self.wfile.write(('ERR '+str(e)+'\n').encode())
        sock = self.root/'control.sock'
        sock.unlink(missing_ok=True)
        self.control = socketserver.ThreadingUnixStreamServer(str(sock), Control)
        self.control.daemon_threads = True
        threading.Thread(target=self.control.serve_forever, daemon=True).start()

    def link(self, left, lif, right, rif, la, ra, mac=None):
        tag = str(time.time_ns())[-7:]
        a, b = 'a'+tag, 'b'+tag
        run(['ip','link','add',a,'type','veth','peer','name',b])
        run(['ip','link','set',a,'netns',pid(left)])
        run(['ip','link','set',b,'netns',pid(right)])
        for name, old, new, addr in [(left,a,lif,la),(right,b,rif,ra)]:
            net(name,'ip','link','set',old,'name',new)
            if addr: net(name,'ip','addr','replace',addr,'dev',new)
            if mac and name == left: net(name,'ip','link','set',new,'address',mac)
            net(name,'ip','link','set',new,'up')

    def copy_host_binary(self, name, path):
        paths = [path]
        for line in run(['ldd',path],check=False).stdout.splitlines():
            for word in line.split():
                if word.startswith('/') and Path(word).is_file(): paths.append(word)
        archive=self.root/'host-runtime.tar'
        with tarfile.open(archive,'w') as tar:
            for path in set(paths):
                if path not in ['/usr/sbin/ip','/usr/sbin/xtables-nft-multi'] and dex(name, 'test -e '+shlex.quote(path),check=False).returncode == 0:
                    continue
                tar.add(Path(path).resolve(),arcname=path.lstrip('/'),recursive=False)
        dex(name,'tar -xf /lab/host-runtime.tar -C /')

    def provision(self):
        run(['gcc','-static','-O2','-o',self.root/'engine-fixture',self.root/'src/tests/fixtures/router_engine.c'])
        for flavor, name in ROUTERS.items():
            run(['nsenter','-t',pid(name),'-u','hostname',name])
            if flavor == 'ow25': dex(name, ': > /etc/apk/repositories.d/distfeeds.list; : > /etc/apk/repositories.d/customfeeds.list')
            elif flavor == 'ow24': dex(name, ': > /etc/opkg/distfeeds.conf; : > /etc/opkg/customfeeds.conf')
            else: dex(name, "sed -i '/^src/d' /opt/etc/opkg.conf")
            if flavor == 'entware':
                for path in ['/usr/sbin/ip','/usr/sbin/xtables-nft-multi']:
                    self.copy_host_binary(name,path)
                dex(name,'mkdir -p /usr/lib/x86_64-linux-gnu/xtables')
                run(['docker','cp','/usr/lib/x86_64-linux-gnu/xtables/.',name+':/usr/lib/x86_64-linux-gnu/xtables/'])
                dex(name,'ln -sf xtables-nft-multi /usr/sbin/iptables; ln -sf xtables-nft-multi /usr/sbin/ip6tables; ln -sf xtables-nft-multi /usr/sbin/iptables-save; ln -sf xtables-nft-multi /usr/sbin/ip6tables-save')
            else:
                source = self.root/('mnt-used24' if flavor == 'ow24' else 'mnt-used25')
                files = [source/'usr/bin/curl'] + list((source/'usr/lib').glob('lib*.so*'))
                paths = ['/'+str(file.relative_to(source)) for file in files]
                query='for f in '+shlex.join(paths)+'; do test -e "$f" || echo "$f"; done'
                missing=dex(name,query).stdout.splitlines()
                archive=self.root/(flavor+'-runtime.tar')
                with tarfile.open(archive,'w') as tar:
                    for path in missing: tar.add(source/path.lstrip('/'),arcname=path.lstrip('/'),recursive=False)
                dex(name,'tar -xf /lab/'+archive.name+' -C /')
                dex(name,'/etc/init.d/network stop; /etc/init.d/cron stop; /etc/init.d/dnsmasq stop',check=False)
            dex(name,'curl --version | head -1')
        self.build_packages()

    def make_ipk(self, data, name, version, path):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w:gz') as tar:
            content = f'Package: {name}\nVersion: {version}\nArchitecture: all\nDescription: isolated matrix fixture\n'.encode()
            info=tarfile.TarInfo('./control'); info.size=len(content)
            tar.addfile(info,io.BytesIO(content))
        payload=io.BytesIO()
        with tarfile.open(fileobj=payload,mode='w:gz') as tar:
            tar.add(data,arcname='.')
        with tarfile.open(path,'w:gz') as tar:
            for filename, content in [('debian-binary',b'2.0\n'),('control.tar.gz',buf.getvalue()),('data.tar.gz',payload.getvalue())]:
                info=tarfile.TarInfo('./'+filename);info.size=len(content);tar.addfile(info,io.BytesIO(content))

    def build_packages(self):
        src=self.root/'src'
        bins=self.root/'bins'; bins.mkdir(exist_ok=True)
        shutil.copy2(self.root/'engine-fixture',bins/'trusttunnel_client-x86_64')
        for name in ['age','age-keygen']:
            file=bins/(name+'-x86_64')
            public = 'age1' + 'q'*58
            source = f'#!/bin/sh\ncase "${{1:-}}" in -y) echo {public} ;; *) echo "# public key: {public}"; echo AGE-SECRET-KEY-1FIXTURE ;; esac\n' if name == 'age-keygen' else '#!/bin/sh\nexit 0\n'
            file.write_text(source); file.chmod(0o755)
        # Package fixtures use the repository's existing public verification key.
        home=self.root/'home'; (home/'tt-build/TTC-clean').mkdir(parents=True,exist_ok=True)
        (home/'tt-build/TTC-clean/LICENSE').write_text('isolated test fixture\n')
        for patch in ['0001-anti-dpi-desync.patch','0002-network-monitor-policy-routing.patch']:
            (src/'engine').mkdir(exist_ok=True);(src/'engine'/patch).write_text('fixture package; no engine patch applied\n')
        env=dict(os.environ, HOME=str(home), ROUTER_BIN=str(bins), AGE_LICENSE=str(home/'tt-build/TTC-clean/LICENSE'),
                 APK=os.environ['CATTUNNEL_APK'], UPDATE_SIGNING_KEY=str(self.root/'absent-key'))
        for version in ['9.159.1','9.159.2']:
            run(['bash',src/'build_packages.sh',version,'x86_64'],env=env,timeout=60)
            dest=self.root/version; shutil.copytree(src/'build',dest,dirs_exist_ok=True)
        # Real curl is present above; empty packages register the provided runtime
        # and host TUN support without contacting external package repositories.
        empty=self.root/'empty';empty.mkdir(exist_ok=True)
        for dep in ['curl','kmod-tun']:
            self.make_ipk(empty,dep,'9.159.0',self.root/(dep+'.ipk'))
            run([os.environ['CATTUNNEL_APK'],'mkpkg','--files',empty,'--info','name:'+dep,
                 '--info','version:9.159.0-r0','--info','arch:noarch','--info','description:isolated fixture',
                 '--output',self.root/(dep+'.apk')],env=dict(os.environ,LD_LIBRARY_PATH=str(Path(os.environ['CATTUNNEL_APK']).resolve().parent)))
        for flavor,name in ROUTERS.items():
            if flavor=='ow25': dex(name,'apk add --allow-untrusted /lab/curl.apk /lab/kmod-tun.apk')
            elif flavor=='ow24': dex(name,'opkg install /lab/curl.ipk /lab/kmod-tun.ipk')
            # Entware already has curl; no kmod dependency there.
        # The only source change inside the lab package replaces the public probe
        # endpoint with an isolated HTTP-204 endpoint, never a foreign service.
        # Rebuild after this adjustment.
        common=src/'common/cattunnel'
        common.write_text(common.read_text().replace('http://connectivitycheck.gstatic.com/generate_204',f'http://{TARGET}:{PORT}/204'))
        common.write_text(common.read_text().replace('wan_ok() {', 'wan_ok() { WAN_WHY=fixture; return 0; }\nwan_ok_unused_in_lab() {'))
        for version in ['9.159.1','9.159.2']:
            run(['bash',src/'build_packages.sh',version,'x86_64'],env=env,timeout=60)
            shutil.copytree(src/'build',self.root/version,dirs_exist_ok=True)
        bad=bins/'trusttunnel_client-x86_64'
        bad.write_text('#!/bin/sh\nexit 7\n');bad.chmod(0o755)
        run(['bash',src/'build_packages.sh','9.159.3','x86_64'],env=env,timeout=60)
        shutil.copytree(src/'build',self.root/'9.159.3',dirs_exist_ok=True)
        shutil.copy2(self.root/'engine-fixture',bad)

    def configure_network(self, flavor, name):
        self.active_router=name
        net(name,'ip','addr','replace','127.0.0.1/8','dev','lo')
        net(name,'ip','link','set','lo','up')
        for endpoint, iface in [('ct159-client','lan0'),('ct159-outside','lan0'),('ct159-exit','wan0')]:
            net(endpoint,'ip','link','del',iface,check=False)
        for iface in ['lan1','lan2','wan','br-lan','tt0']:
            net(name,'ip','link','del',iface,check=False)
        net(name,'ip','link','add','br-lan','type','bridge')
        net(name,'ip','addr','add','10.159.0.1/24','dev','br-lan')
        net(name,'ip','link','set','br-lan','up')
        self.link('ct159-client','lan0',name,'lan1','10.159.0.2/24',None,MAC1)
        self.link('ct159-outside','lan0',name,'lan2','10.159.0.3/24',None,MAC2)
        for iface in ['lan1','lan2']: net(name,'ip','link','set',iface,'master','br-lan')
        self.link(name,'wan','ct159-exit','wan0','198.19.159.1/24','198.19.159.2/24')
        net(name,'ip','route','replace','default','via','198.19.159.2')
        for endpoint in ['ct159-client','ct159-outside']:
            net(endpoint,'ip','route','replace','default','via','10.159.0.1')
            net(endpoint,'ip','link','set','lo','up')
        net('ct159-exit','ip','addr','replace',TARGET+'/32','dev','lo')
        net('ct159-exit','ip','link','set','lo','up')
        net('ct159-exit','ip','route','replace','10.159.0.0/24','via','198.19.159.1')
        net(name,'sysctl','-qw','net.ipv4.ip_forward=1')
        if flavor!='entware':
            dex(name,"uci -q delete 'firewall.@zone[0].network'; uci -q delete 'firewall.@zone[1].network'; uci set 'firewall.@zone[0].device=br-lan'; uci set 'firewall.@zone[1].device=wan'; uci set 'firewall.@zone[0].forward=ACCEPT'; uci commit firewall; /etc/init.d/firewall restart")
        else:
            dex(name,'iptables -P FORWARD ACCEPT; ip6tables -P FORWARD ACCEPT')
        http=self.spawn_net('ct159-exit','python3',self.root/'src/tests/router_matrix.py','--http',logfile=self.root/'http.log')
        self.processes['http']=[http]

    def etc(self, flavor): return '/opt/etc/cattunnel' if flavor=='entware' else '/etc/cattunnel'
    def init(self, flavor): return '/opt/etc/init.d/S99cattunnel' if flavor=='entware' else '/etc/init.d/cattunnel'
    def ct(self, flavor): return '/opt/bin/cattunnel' if flavor=='entware' else '/usr/bin/cattunnel'
    def package(self, flavor, version):
        return f'/lab/{version}/cattunnel-{version}-r0_openwrt25-x86_64.apk' if flavor=='ow25' else f'/lab/{version}/cattunnel_{version}_{"entware" if flavor=="entware" else "openwrt"}-x86_64.ipk'

    def install(self, flavor,name,version,reinstall=False):
        cmd=f'sh /lab/{version}/install.sh --no-luci --from /lab/{version}'
        if reinstall: cmd+=' --reinstall'
        p=dex(name,cmd,check=False,timeout=70)
        return p

    def settings(self, flavor,name,mode,selected):
        etc=self.etc(flavor)
        dex(name,f'mkdir -p {etc}; cat > {etc}/cattunnel.conf <<\'CONF\'\nMODE=\'{mode}\'\nSERVER=\'lab\'\nDEVICES=\'{MAC1 if selected else ""}\'\nKILLSWITCH=\'on\'\nRU_DIRECT=\'off\'\nDNS=\'router\'\nIDLE_STOP=\'0\'\nCHECK_EVERY=\'1\'\nAUTO_WAIT=\'5\'\nSOCKS=\'127.0.0.1:1080\'\nCONF\ncat > {etc}/servers.bundle <<\'BUNDLE\'\n# cattunnel-router 1\n@server lab Laboratory\n[endpoint]\nhostname = "local.invalid"\naddresses = ["198.19.159.2:443"]\nusername = "fixture"\npassword = "fixture"\nBUNDLE')
        dex(name,f"printf '%s %s - fixture\\n' \"$(date +%s)\" 9.159.1 > {etc}/upgrade.state")
        (self.root/f'{name}.json').write_text(json.dumps({'mode':mode,'selected':selected,'delay':.5}))

    def probe(self,flavor,name,timeout=15):
        deadline=time.monotonic()+timeout
        last=''
        while time.monotonic()<deadline:
            p=dex(name,self.ct(flavor)+' test',check=False,timeout=12)
            last=p.stdout+p.stderr
            if p.returncode==0 and dex(name,f'test ! -f {self.etc(flavor)}/upgrade.pending && test ! -f '+('/opt/var/run/cattunnel' if flavor=='entware' else '/var/run/cattunnel')+'/restart.pending',check=False).returncode==0:
                return True
            time.sleep(.2)
        raise RuntimeError('Probe failed: '+last+' '+dex(name,self.ct(flavor)+' log 20',check=False).stdout)

    def http_client(self, endpoint, socks=False):
        args=['curl','-s','--max-time','3','-o','/dev/null','-w','%{http_code}']
        if socks: args+=['--socks5-hostname','10.159.0.1:1080']
        args+=[f'http://{TARGET}:{PORT}/204']
        return net(endpoint,*args,check=False).stdout.strip()=='204'

    def count(self,flavor,name):
        if flavor=='entware': return dex(name,'iptables-save -c; ip6tables-save -c',check=False).stdout
        return dex(name,'nft list ruleset',check=False).stdout

    def traffic(self, phase, duration=.7):
        # UDP probes deliberately attempt a direct/fallback path from both MACs.
        script='''import socket,time,sys
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
end=time.monotonic()+float(sys.argv[2]); n=0
while time.monotonic()<end:
 s.sendto((sys.argv[1]+':'+str(n)).encode(),('198.51.100.159',18081));n+=1;time.sleep(.02)
'''
        procs=[]
        for endpoint,tag in [('ct159-client','selected'),('ct159-outside','outside')]:
            procs.append(subprocess.Popen(['nsenter','-t',str(pid(endpoint)),'-n','python3','-c',script,phase+'-'+tag,str(duration)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE))
        for p in procs:
            _,err=p.communicate(timeout=duration+4)
            if p.returncode: raise RuntimeError(err.decode())

    def senders(self, phase):
        code='''import socket,time,sys
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
while True:
 s.sendto((sys.argv[1]+':'+str(time.time())).encode(),('198.51.100.159',18081))
 time.sleep(.01)
'''
        return [self.spawn_net(endpoint,'python3','-c',code,phase+'-'+tag,
                               logfile=self.root/'senders.log')
                for endpoint,tag in [('ct159-client','selected'),('ct159-outside','outside')]]

    def transition_counts(self,file,start,end):
        text=run(['tcpdump','-nn','-A','-r',file],check=False).stdout
        counts={'selected':0,'outside':0}
        for tag, timestamp in re.findall(r'transition-(selected|outside):([0-9.]+)',text):
            if start <= float(timestamp) <= end: counts[tag]+=1
        return counts

    def capture(self,name,file):
        return self.spawn_net(name,'tcpdump','-i','wan','-nn','-U','-w',file,
                              'dst host '+TARGET+' and udp dst port 18081',logfile=str(file)+'.log')

    def capture_tags(self,file):
        p=run(['tcpdump','-nn','-A','-r',file],check=False)
        text=p.stdout
        return {'selected':text.count('-selected:'),'outside':text.count('-outside:')}

    def row(self,flavor,name,mode,selected,operation):
        directory=self.root/'evidence'/f'{flavor}-{mode}-{int(selected)}-{operation}'
        directory.mkdir(parents=True,exist_ok=True)
        result={'platform':flavor,'mode':mode,'devices':bool(selected),'operation':operation}
        # Start each operation from a known package and live engine.
        dex(name,self.init(flavor)+' stop',check=False)
        self.stop_engine(name)
        dex(name,'rm -f '+self.etc(flavor)+'/upgrade.pending '+self.etc(flavor)+'/autostart.off; rm -rf '+self.etc(flavor)+'/upgrade.lock',check=False)
        pm='apk del cattunnel' if flavor=='ow25' else ('/opt/bin/opkg' if flavor=='entware' else 'opkg')+' remove cattunnel'
        dex(name,pm,check=False)
        self.settings(flavor,name,mode,selected)
        p=self.install(flavor,name,'9.159.1',reinstall=True)
        (directory/'prepare.log').write_text(p.stdout+p.stderr)
        if p.returncode: raise RuntimeError('prepare install failed: '+p.stdout+p.stderr)
        dex(name,self.init(flavor)+' restart')
        self.probe(flavor,name)
        result['before_http']=self.http_client('ct159-client',socks=mode=='socks')
        if not result['before_http']:
            (directory/'baseline.rules').write_text(self.count(flavor,name))
            (directory/'baseline.routes').write_text(net(name,'ip','route','show','table','all').stdout+net(name,'ip','rule','show').stdout)
            capture=self.spawn_net(name,'tcpdump','-i','any','-nn','-l','tcp port 18080',logfile=directory/'baseline.tcpdump')
            debug=net('ct159-client','curl','-v','--max-time','4',f'http://{TARGET}:{PORT}/204',check=False)
            self.stop_process(capture)
            (directory/'baseline.curl').write_text(debug.stdout+debug.stderr)
            raise RuntimeError('baseline client HTTP failed')
        # Capturing a deliberately held stop interval gives deterministic packet
        # evidence, followed by the actual public command/installer transition.
        if operation in ['upgrade','reinstall','restart','rollback']:
            if operation in ['upgrade','reinstall','rollback']:
                dex(name,'touch '+self.etc(flavor)+'/upgrade.pending')
            dex(name,self.ct(flavor)+' stop --keep-rules')
            self.stop_engine(name)
            capture=self.capture(name,directory/'during.pcap')
            time.sleep(.15)
            self.traffic('during')
            counters=self.count(flavor,name)
            (directory/'during.rules').write_text(counters)
            if flavor=='entware':
                drops=[int(n) for n in re.findall(r'\[(\d+):\d+\] -A CT_UP_[FP]_[AB].* -j DROP',counters)]
            else:
                drops=[int(n) for n in re.findall(r'chain blocked \{\s*counter packets (\d+)',counters)]
            result['drop_counter']=sum(drops)
            if not result['drop_counter']: raise RuntimeError('temporary drop counter did not increase')
            if selected:
                result['outside_http_during']=self.http_client('ct159-outside')
                if not result['outside_http_during']: raise RuntimeError('outside HTTP interrupted by scoped barrier')
            self.stop_process(capture)
            result['during']=self.capture_tags(directory/'during.pcap')
            expected_outside=selected
            result['blocked_selected']=result['during']['selected']==0
            result['outside_continues']=bool(result['during']['outside'])==expected_outside
            if not result['blocked_selected'] or not result['outside_continues']:
                raise RuntimeError('packet barrier mismatch '+str(result['during']))
            # Restore a live baseline; the next capture starts BEFORE the real
            # public operation, so a pre-installed test barrier cannot hide a gap.
            dex(name,self.init(flavor)+' restart')
            self.probe(flavor,name)
            capture=self.capture(name,directory/'transition.pcap')
            senders=self.senders('transition')
            operation_start=time.time()
            if operation=='restart':
                dex(name,self.init(flavor)+' restart')
            elif operation=='rollback':
                # The normal installer is executed against a real package manager;
                # the engine version check in a dedicated broken package causes failure.
                p=self.install(flavor,name,'9.159.3',reinstall=False)
                (directory/'operation.log').write_text(p.stdout+p.stderr)
                result['install_rc']=p.returncode
                if p.returncode==0: raise RuntimeError('broken update unexpectedly succeeded')
            else:
                version='9.159.2' if operation=='upgrade' else '9.159.1'
                p=self.install(flavor,name,version,reinstall=operation=='reinstall')
                (directory/'operation.log').write_text(p.stdout+p.stderr)
                if p.returncode: raise RuntimeError('installer failed: '+p.stdout+p.stderr)
            self.probe(flavor,name)
            for sender in senders: self.stop_process(sender)
            self.stop_process(capture)
            events=[e for e in self.events if e['router']==name and e['time']>=operation_start]
            (directory/'events.json').write_text(json.dumps(events,indent=2))
            stopped=next(e['time'] for e in events if e['event']=='stop')
            ready=next(e['time'] for e in events if e['event']=='ready')
            result['transition']=self.transition_counts(directory/'transition.pcap',stopped,ready)
            if result['transition']['selected'] != 0: raise RuntimeError('actual transition leak '+str(result['transition']))
            if selected and not result['transition']['outside']: raise RuntimeError('outside device interrupted during actual transition')
            result['after_http']=False
            for retry in range(5):
                if self.http_client('ct159-client',socks=mode=='socks'):
                    result['after_http']=True; break
                time.sleep(.2)
            if not result['after_http']:
                (directory/'recovery.rules').write_text(self.count(flavor,name))
                (directory/'recovery.routes').write_text(net(name,'ip','route','show','table','all').stdout+net(name,'ip','rule','show').stdout)
                raise RuntimeError('recovery HTTP failed')
        else:
            if operation in ['stop-force', 'remove-pending']:
                dex(name, 'touch '+self.etc(flavor)+'/upgrade.pending')
                dex(name, self.ct(flavor)+' hold')
            if operation=='stop': dex(name,self.init(flavor)+' stop')
            elif operation=='stop-force': dex(name,self.ct(flavor)+' stop --force')
            elif operation in ['reinstall-stopped', 'reinstall-autostart-off']:
                dex(name,self.ct(flavor)+' stop --force')
                if operation=='reinstall-autostart-off': dex(name,self.ct(flavor)+' autostart off')
                p=self.install(flavor,name,'9.159.2',reinstall=True)
                (directory/'operation.log').write_text(p.stdout+p.stderr)
                if p.returncode: raise RuntimeError('stopped service reinstall failed: '+p.stdout+p.stderr)
                rundir='/opt/var/run/cattunnel' if flavor=='entware' else '/var/run/cattunnel'
                dex(name, f'test ! -f {self.etc(flavor)}/upgrade.pending && test ! -f {rundir}/restart.pending && test ! -f {rundir}/run.pid')
            elif operation in ['remove', 'remove-pending']:
                pm='apk del cattunnel' if flavor=='ow25' else ('/opt/bin/opkg' if flavor=='entware' else 'opkg')+' remove cattunnel'
                p=dex(name,pm,check=False);(directory/'operation.log').write_text(p.stdout+p.stderr)
                if p.returncode: raise RuntimeError('remove failed: '+p.stdout+p.stderr)
            self.stop_engine(name)
            capture=self.capture(name,directory/'after.pcap');time.sleep(.15)
            self.traffic('after')
            (directory/'after.rules').write_text(self.count(flavor,name));self.stop_process(capture)
            result['after']=self.capture_tags(directory/'after.pcap')
            result['direct_restored']=all(result['after'][k]>0 for k in ['selected','outside'])
            if not result['direct_restored']: raise RuntimeError('direct Internet not restored '+str(result['after']))
            result['after_http']=self.http_client('ct159-client')
            if not result['after_http']: raise RuntimeError('direct client HTTP failed')
        if operation=='reinstall-autostart-off': dex(name,self.ct(flavor)+' autostart on')
        result['pass']=True
        (directory/'result.json').write_text(json.dumps(result,indent=2))
        return result

    def matrix(self):
        saved=self.root/'results.json'
        source_hash=matrix_source_hash(self.root/'src')
        if saved.exists():
            self.rows=[r for r in json.loads(saved.read_text()) if r.get('pass') and r.get('source_sha256')==source_hash]
        self.start_control()
        for flavor,name in ROUTERS.items():
            self.configure_network(flavor,name)
            for mode in ['tun','socks']:
                for selected in [False,True]:
                    for operation in ['upgrade','reinstall','restart','stop','remove','rollback',
                                      'stop-force','remove-pending','reinstall-stopped','reinstall-autostart-off']:
                        if any((r['platform'],r['mode'],r['devices'],r['operation'])==(flavor,mode,selected,operation) for r in self.rows): continue
                        try: row=self.row(flavor,name,mode,selected,operation)
                        except Exception as e:
                            row={'platform':flavor,'mode':mode,'devices':selected,'operation':operation,'pass':False,'error':str(e)}
                        row['source_sha256']=source_hash
                        self.rows.append(row)
                        (self.root/'results.json').write_text(json.dumps(self.rows,indent=2))
                        print(json.dumps(row),flush=True)
                        if not row['pass']: raise RuntimeError(str(row))
            dex(name,self.init(flavor)+' stop',check=False)
            self.stop_engine(name)
            for proc in self.processes.pop('http',[]): self.stop_process(proc)

    def ipv6(self):
        target6='2001:db8:159::159'
        rows=[]
        for flavor,name in ROUTERS.items():
            dex(name,'rm -f '+self.etc(flavor)+'/upgrade.pending; rm -rf '+self.etc(flavor)+'/upgrade.lock',check=False)
            dex(name,self.init(flavor)+' stop',check=False)
            self.configure_network(flavor,name)
            for endpoint in [name,'ct159-client','ct159-outside','ct159-exit']:
                net(endpoint,'sysctl','-qw','net.ipv6.conf.all.disable_ipv6=0')
            for endpoint,iface,address in [(name,'br-lan','fd00:159:1::1/64'),(name,'wan','fd00:159:2::1/64'),
                ('ct159-client','lan0','fd00:159:1::2/64'),('ct159-outside','lan0','fd00:159:1::3/64'),
                ('ct159-exit','wan0','fd00:159:2::2/64'),('ct159-exit','lo',target6+'/128')]:
                net(endpoint,'ip','-6','addr','replace',address,'dev',iface,'nodad')
            for endpoint in ['ct159-client','ct159-outside']:
                net(endpoint,'ip','-6','route','replace','default','via','fd00:159:1::1')
            net(name,'sysctl','-qw','net.ipv6.conf.all.forwarding=1')
            net(name,'ip','-6','route','replace','default','via','fd00:159:2::2')
            net('ct159-exit','ip','-6','route','replace','fd00:159:1::/64','via','fd00:159:2::1')
            http6=self.spawn_net('ct159-exit','python3',self.root/'src/tests/router_matrix.py','--http6',logfile=self.root/'http6.log')
            self.processes['http6']=[http6]
            time.sleep(.2)
            for mode in ['tun','socks']:
                for selected in [False,True]:
                    self.settings(flavor,name,mode,selected)
                    if selected:
                        # Exercise the same name/prefix resolution as the real
                        # DHCP device selector rather than only literal MACs.
                        dex(name,f"sed -i \"s/{MAC1}/lab-phone*/\" {self.etc(flavor)}/cattunnel.conf; printf '9999999999 {MAC1} 10.159.0.2 lab-phone-one *\\n' > /tmp/dhcp.leases")
                    directory=self.root/'evidence'/f'ipv6-{flavor}-{mode}-{int(selected)}'
                    directory.mkdir(parents=True,exist_ok=True)
                    baseline=net('ct159-outside','curl','-g','-6','-s','--max-time','3','-o','/dev/null','-w','%{http_code}',f'http://[{target6}]:{PORT}/204',check=False)
                    if baseline.stdout!='204': raise RuntimeError('IPv6 baseline failed '+baseline.stdout+baseline.stderr)
                    share='/opt/usr/share/cattunnel' if flavor=='entware' else '/usr/share/cattunnel'
                    dex(name,f'. {share}/upgrade.sh; upgrade_guard on {self.etc(flavor)}')
                    if flavor=='entware':
                        # Emulate deletion of our rules by firmware, then call
                        # the installed hook while the engine remains stopped.
                        dex(name,f'touch {self.etc(flavor)}/upgrade.pending; . {share}/upgrade.sh; upgrade_guard off; type=ip6tables table=filter /opt/etc/ndm/netfilter.d/50-cattunnel.sh; rm {self.etc(flavor)}/upgrade.pending')
                    else:
                        dex(name,'/etc/init.d/firewall reload')
                    capture=self.spawn_net(name,'tcpdump','-i','wan','-nn','-U','-w',directory/'during.pcap',
                        'dst host '+target6+' and udp dst port 18081',logfile=directory/'capture.log')
                    time.sleep(.1)
                    code='''import socket,time,sys
s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM)
for n in range(30):
 s.sendto((sys.argv[1]+':'+str(n)).encode(),('2001:db8:159::159',18081));time.sleep(.02)
'''
                    def send():
                        procs=[self.spawn_net(endpoint,'python3','-c',code,'ipv6-'+tag,logfile=directory/'senders.log')
                            for endpoint,tag in [('ct159-client','selected'),('ct159-outside','outside')]]
                        for proc in procs: proc.wait(timeout=4)
                    send()
                    counters=self.count(flavor,name)
                    (directory/'during.rules').write_text(counters)
                    self.stop_process(capture)
                    during=self.capture_tags(directory/'during.pcap')
                    if during['selected'] or bool(during['outside'])!=selected:
                        raise RuntimeError('IPv6 scoped barrier mismatch '+str(during))
                    dex(name,self.init(flavor)+' stop')
                    capture=self.spawn_net(name,'tcpdump','-i','wan','-nn','-U','-w',directory/'after.pcap',
                        'dst host '+target6+' and udp dst port 18081',logfile=directory/'capture-after.log')
                    time.sleep(.1);send();self.stop_process(capture)
                    after=self.capture_tags(directory/'after.pcap')
                    if not all(after.values()): raise RuntimeError('IPv6 user stop did not restore direct traffic '+str(after))
                    row={'platform':flavor,'mode':mode,'devices':selected,'name_resolution':selected,'firewall_reload_or_hook':True,'during':during,'after_stop':after,'pass':True}
                    rows.append(row)
                    (self.root/'ipv6-results.json').write_text(json.dumps(rows,indent=2))
                    print(json.dumps(row),flush=True)
            for key in ['http','http6']:
                for proc in self.processes.pop(key,[]): self.stop_process(proc)

    def dns_cleanup(self):
        rows=[]
        for flavor,name in ROUTERS.items():
            dex(name,'rm -f '+self.etc(flavor)+'/upgrade.pending; rm -rf '+self.etc(flavor)+'/upgrade.lock',check=False)
            dex(name,self.init(flavor)+' stop',check=False)
            self.settings(flavor,name,'tun',flavor=='entware')
            etc=self.etc(flavor)
            dex(name,f"printf '\\ndns_upstreams = [\"198.18.159.2\"]\\n' >> {etc}/servers.bundle; {self.ct(flavor)} set DNS tunnel")
            directory=self.root/'evidence'/f'dns-stop-{flavor}'
            directory.mkdir(parents=True,exist_ok=True)
            if flavor=='entware':
                dex(name,self.ct(flavor)+' devices on lab')
                before=self.count(flavor,name)
                if 'CATTUNNEL_DNS' not in before: raise RuntimeError('DNS fixture rules missing')
            else:
                dex(name,self.ct(flavor)+' dns on')
                before=dex(name,'uci show dhcp').stdout
                if '.cattunnel=' not in before: raise RuntimeError('DNS fixture marker missing')
            (directory/'before.txt').write_text(before)
            dex(name,self.init(flavor)+' stop')
            after=self.count(flavor,name) if flavor=='entware' else dex(name,'uci show dhcp').stdout
            (directory/'after.txt').write_text(after)
            if ('CATTUNNEL_DNS' in after if flavor=='entware' else any(x in after for x in ['.cattunnel=','.noresolv=','198.18.159.2'])):
                raise RuntimeError('DNS stop cleanup failed')
            rules=net(name,'ip','rule','show').stdout+net(name,'ip','-6','rule','show').stdout
            (directory/'after.iprules').write_text(rules)
            if 'lookup 218' in rules: raise RuntimeError('DEVICES policy left after stop')
            row={'platform':flavor,'dns_rules_removed':True,'devices_policy_removed':True,'pass':True}
            rows.append(row)
            (self.root/'dns-results.json').write_text(json.dumps(rows,indent=2))
            print(json.dumps(row),flush=True)

    def exchange_import(self):
        rows = []
        for flavor, name in ROUTERS.items():
            self.configure_network(flavor, name)
            self.settings(flavor, name, 'socks', False)
            install = self.install(flavor, name, '9.159.2', reinstall=True)
            if install.returncode:
                raise RuntimeError('exchange fixture install failed: '+install.stdout+install.stderr)
            cli = self.ct(flavor)
            etc = self.etc(flavor)
            directory = self.root/'evidence'/('exchange-'+flavor)
            directory.mkdir(parents=True, exist_ok=True)
            origin = 'http://198.19.159.2:18080'
            for url in [origin+'/api/go/valid-code',
                        'cattunnel://subscription?code=valid-code&base=http%3A%2F%2F198.19.159.2%3A18080']:
                imported = dex(name, cli+' import '+shlex.quote(url), check=False)
                (directory/('import-'+str(len(rows))+'.log')).write_text(imported.stdout+imported.stderr)
                if imported.returncode:
                    raise RuntimeError('one-time import failed: '+imported.stderr)
                saved = dex(name, 'cat '+etc+'/cattunnel.conf').stdout
                if f"SUB_URL='{origin}/subscription'" not in saved or 'valid-code' in saved:
                    raise RuntimeError('one-time code persisted or subscription URL missing')
                if 'AGE-SECRET' in saved:
                    raise RuntimeError('private identity copied into settings')
                rows.append({'platform':flavor, 'kind':'deep' if url.startswith('cattunnel:') else 'web', 'pass':True})
            before = dex(name, 'sha256sum '+etc+'/cattunnel.conf '+etc+'/servers.bundle '+etc+'/device.key').stdout
            for code, expected in [('expired-code','истекла'), ('bad-code','отклонил'), ('missing-code','не найдена')]:
                failed = dex(name, cli+' import '+shlex.quote(origin+'/api/go/'+code), check=False)
                (directory/(code+'.log')).write_text(failed.stdout+failed.stderr)
                if failed.returncode == 0 or expected not in failed.stderr:
                    raise RuntimeError('wrong exchange error: '+failed.stdout+failed.stderr)
                after = dex(name, 'sha256sum '+etc+'/cattunnel.conf '+etc+'/servers.bundle '+etc+'/device.key').stdout
                if before != after:
                    raise RuntimeError('failed exchange changed saved subscription or identity')
                rows.append({'platform':flavor, 'kind':code, 'pass':True})
            dex(name, cli+' stop --force')
            self.stop_engine(name)
            for proc in self.processes.pop('http', []): self.stop_process(proc)
        (self.root/'exchange-results.json').write_text(json.dumps(rows, indent=2))
        print(json.dumps(rows), flush=True)

    def close(self, remove=False):
        try:
            if self.safe:
                self.quiesce()
            for proc in self.all_processes: self.stop_process(proc)
            for name in list(self.processes):
                for proc in self.processes.pop(name,[]): self.stop_process(proc)
            if self.control:
                self.control.shutdown(); self.control.server_close()
                (self.root/'control.sock').unlink(missing_ok=True)
            if remove:
                remove_containers()
        finally:
            # Last cleanup operation; an active or unreadable watchdog is a hard failure.
            check_watchdog()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('/tmp/cattunnel-matrix'))
    parser.add_argument('--provision',action='store_true')
    parser.add_argument('--cleanup',action='store_true')
    parser.add_argument('--http',action='store_true')
    parser.add_argument('--http6',action='store_true')
    parser.add_argument('--ipv6',action='store_true')
    parser.add_argument('--dns-cleanup',action='store_true')
    parser.add_argument('--exchange-import',action='store_true')
    parser.add_argument('--socks',action='store_true')
    args=parser.parse_args()
    if args.http: serve_http()
    elif args.http6: serve_http6()
    elif args.socks: serve_socks()
    else:
        matrix=Matrix(args.root)
        try:
            if not args.cleanup:
                preflight()
                matrix.safe = True
                matrix.quiesce()
            if args.cleanup: pass
            elif args.provision: matrix.provision()
            elif args.ipv6: matrix.ipv6()
            elif args.dns_cleanup: matrix.dns_cleanup()
            elif args.exchange_import: matrix.exchange_import()
            else: matrix.matrix()
        finally: matrix.close(remove=args.cleanup)
