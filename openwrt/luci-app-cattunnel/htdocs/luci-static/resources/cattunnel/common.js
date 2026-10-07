'use strict';
'require baseclass';
'require fs';
'require ui';

const CT = '/usr/bin/cattunnel';

return baseclass.extend({
	/* cattunnel <args...> -> { code, stdout, stderr } (exec errors become code -1) */
	run(args) {
		return fs.exec(CT, args).catch((e) => ({ code: -1, stdout: '', stderr: String(e) }));
	},

	json(what) {
		return this.run([ 'json', what ]).then((r) => {
			try { return JSON.parse(r.stdout); } catch (e) { return null; }
		});
	},

	service(action) {
		return fs.exec('/etc/init.d/cattunnel', [ action ]).catch(() => null);
	},

	/* run, then show what happened; resolves to the result */
	act(args, okText) {
		return this.run(args).then((r) => {
			const text = (r.stdout || '') + (r.stderr || '');
			if (r.code === 0)
				ui.addNotification(null, E('p', okText || text.trim() || 'Готово'), 'info');
			else
				ui.addNotification(null, E('pre', text.trim() || ('Ошибка ' + r.code)), 'danger');
			return r;
		});
	},

	modeName(mode) {
		return mode === 'tun' ? 'весь LAN через туннель (tun)' : 'SOCKS5 для mihomo';
	}
});
