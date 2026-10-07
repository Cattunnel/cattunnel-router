'use strict';
/* Прослойка вместо LuCI для Keenetic / ASUS Merlin: запускает ТЕ ЖЕ страницы CatTunnel, что и LuCI на
 * OpenWrt (luci/view/cattunnel/*.js, кладутся в пакет при сборке), — одна кодовая база, одинаковые
 * возможности. Реализовано ровно то, чем эти страницы пользуются: E(), dom.content, ui.addNotification,
 * ui.showModal/hideModal, ui.createHandlerFn, poll.add, fs.exec, view.extend, baseclass.extend.
 * fs.exec идёт в cgi-bin/api (action=exec), где разрешены те же команды, что в ACL LuCI. */
(function () {
	function append(node, children) {
		if (children == null || children === false || children === '') return;
		if (Array.isArray(children)) { children.forEach((c) => append(node, c)); return; }
		if (children instanceof Node) { node.appendChild(children); return; }
		node.appendChild(document.createTextNode(String(children)));
	}

	function E(tag, attrs, children) {
		const node = document.createElement(tag);
		if (attrs != null && (Array.isArray(attrs) || attrs instanceof Node || typeof attrs !== 'object')) { children = attrs; attrs = null; }
		if (attrs) Object.keys(attrs).forEach((k) => {
			const v = attrs[k];
			if (v == null) return;
			if (typeof v === 'function') node.addEventListener(k, v);
			else if (typeof v === 'object') node.setAttribute(k, JSON.stringify(v));
			else node.setAttribute(k, v);
		});
		append(node, children);
		return node;
	}

	const dom = {
		content(node, children) { while (node.firstChild) node.removeChild(node.firstChild); append(node, children); return node; }
	};

	let modal = null;
	const ui = {
		addNotification(title, children, cls) {
			const box = document.getElementById('notifications');
			const n = E('div', { 'class': 'alert-message ' + (cls || 'info') }, [ title ? E('h4', {}, title) : '', children ]);
			n.addEventListener('click', () => n.remove());
			box.appendChild(n);
			setTimeout(() => n.remove(), cls === 'danger' ? 15000 : 6000);
			return n;
		},
		showModal(title, children) {
			ui.hideModal();
			modal = E('div', { 'class': 'modal-overlay' }, E('div', { 'class': 'modal' }, [ title ? E('h4', {}, title) : '', children ]));
			document.body.appendChild(modal);
			return modal;
		},
		hideModal() { if (modal) { modal.remove(); modal = null; } },
		createHandlerFn(ctx, fn, ...args) {
			if (typeof fn === 'string') fn = ctx[fn];
			return function (ev) {
				const btn = ev && ev.currentTarget;
				if (btn && btn.tagName === 'BUTTON') btn.disabled = true;
				return Promise.resolve().then(() => fn.apply(ctx, args.concat([ ev ])))
					.catch((e) => ui.addNotification(null, E('pre', String(e)), 'danger'))
					.finally(() => { if (btn && btn.tagName === 'BUTTON') btn.disabled = false; });
			};
		}
	};

	let polls = [];
	const poll = { add(fn, interval) { const id = setInterval(() => { Promise.resolve().then(fn).catch(() => {}); }, (interval || 5) * 1000); polls.push(id); return id; } };
	function stopPolls() { polls.forEach(clearInterval); polls = []; }

	const fs = {
		exec(cmd, args) {
			const body = new URLSearchParams();
			body.append('action', 'exec');
			body.append('cmd', cmd);
			(args || []).forEach((a, i) => body.append('a' + i, String(a)));
			return fetch('cgi-bin/api', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
				headers: { 'X-CatTunnel': '1', 'Content-Type': 'application/x-www-form-urlencoded' }, body: body.toString() })
				.then((r) => r.json())
				.then((j) => ({ code: j.code, stdout: j.stdout || '', stderr: j.stderr || '' }));
		}
	};

	const view = { extend(o) { return o; } };
	const baseclass = { extend(o) { return o; } };

	const cache = {};
	function loadModule(path, deps) {
		if (cache[path]) return cache[path];
		cache[path] = fetch(path, { cache: 'no-store' }).then((r) => { if (!r.ok) throw new Error(path + ': ' + r.status); return r.text(); })
			.then((src) => new Function('view', 'ui', 'dom', 'poll', 'fs', 'baseclass', 'ct', 'E', src)(view, ui, dom, poll, fs, baseclass, deps.ct, E));
		return cache[path];
	}

	const PAGES = [ [ 'status', 'Состояние' ], [ 'servers', 'Серверы' ], [ 'settings', 'Настройки' ], [ 'diagnostics', 'Диагностика' ], [ 'help', 'Справка' ] ];

	function show(page) {
		stopPolls(); ui.hideModal();
		document.querySelectorAll('#tabs a').forEach((a) => {
			a.classList.toggle('active', a.dataset.page === page);
			if (a.dataset.page === page) a.scrollIntoView({ block: 'nearest', inline: 'nearest' });   // на телефоне вкладки прокручиваются
		});
		const main = document.getElementById('view');
		dom.content(main, E('p', { 'class': 'loading' }, 'Загружаю…'));
		loadModule('luci/cattunnel/common.js', {}).then((ct) =>
			// каждый показ — свежий экземпляр страницы (как в LuCI при переходе)
			fetch('luci/view/cattunnel/' + page + '.js', { cache: 'no-store' }).then((r) => r.text())
				.then((src) => new Function('view', 'ui', 'dom', 'poll', 'fs', 'baseclass', 'ct', 'E', src)(view, ui, dom, poll, fs, baseclass, ct, E)))
			.then((v) => Promise.resolve(v.load ? v.load() : null).then((d) => v.render(d)))
			.then((node) => dom.content(main, node))
			.catch((e) => dom.content(main, E('div', { 'class': 'alert-message danger' }, 'Страница не загрузилась: ' + e)));
		if (location.hash !== '#' + page) { try { history.pushState(null, '', '#' + page); } catch (e) {} }
	}

	/* Марсик в шапке: глаза — состояние туннеля (раз в 10 с, независимо от вкладки) */
	function headerState() {
		return fs.exec('/usr/bin/cattunnel', [ 'json', 'status' ]).then((r) => {
			let s = null; try { s = JSON.parse(r.stdout); } catch (e) {}
			const cat = document.getElementById('marsik'), line = document.getElementById('who-state');
			if (!s || s.broken) { cat.dataset.state = 'down'; line.textContent = s && s.broken ? s.broken : 'Не получается узнать состояние'; return; }
			if (s.running) { cat.dataset.state = 'up'; line.textContent = 'Туннель работает, сервер ' + (s.server_name || s.server); }
			else if (s.waiting_devices) { cat.dataset.state = 'wait'; line.textContent = 'Ждёт устройства: туннель поднимется, когда они выйдут в интернет'; }
			else { cat.dataset.state = 'down'; line.textContent = s.subscription ? 'Туннель остановлен' : 'Нет подписки: добавьте её в «Настройках»'; }
		}).catch(() => { document.getElementById('marsik').dataset.state = 'unknown'; document.getElementById('who-state').textContent = 'Роутер не отвечает'; });
	}

	window.addEventListener('DOMContentLoaded', () => {
		headerState(); setInterval(headerState, 10000);
		const tabs = document.getElementById('tabs');
		PAGES.forEach(([ p, t ]) => tabs.appendChild(E('a', { 'href': '#' + p, 'data-page': p, 'click': (ev) => { ev.preventDefault(); show(p); } }, t)));
		// «назад»/ссылка с #вкладкой — переключить без перезагрузки
		window.addEventListener('hashchange', () => { const h = location.hash.slice(1); if (PAGES.some(([ p ]) => p === h)) show(h); });
		const start = (location.hash || '').slice(1);
		show(PAGES.some(([ p ]) => p === start) ? start : 'status');
	});
	window.E = E;
	window.CT_STANDALONE = true;   // отдельная страница, не LuCI (settings.js прячет «Выключить страницу»)
	window.L = { resource(p) { return 'luci/' + p; } };   // L.resource — как в LuCI (страница «Справка»)
})();
