'use strict';
'require view';
'require poll';
'require ui';
'require dom';
'require cattunnel.common as ct';

function row(label, value) {
	return E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td left', 'width': '33%' }, label), E('td', { 'class': 'td left' }, value) ]);
}

return view.extend({
	load() { return Promise.all([ ct.json('status'), ct.json('doctor') ]); },

	renderTable(s) {
		if (!s)
			return E('p', {}, 'cattunnel не отвечает — пакет установлен?');
		if (s.broken)
			return E('div', { 'class': 'alert-message error' }, [ E('p', {}, s.broken) ]);
		if (!s.subscription)
			return E('div', { 'class': 'alert-message warning' }, [
				E('p', {}, 'Подписки ещё нет. Откройте «Настройки» и вставьте ссылку и ключ — те же, что в приложении CatTunnel.')
			]);
		const dpi = s.auto ? ('авто' + (s.auto_mode ? ', сработал способ ' + s.auto_mode : ', подбирается')) : 'как в подписке';
		return E('table', { 'class': 'table' }, [
			row('Состояние', s.running ? E('strong', { 'style': 'color:#2e7d32' }, '● работает') :
				s.waiting_devices ? E('strong', { 'style': 'color:#1565c0' }, '● ждёт устройства — туннель поднимется, когда они появятся в сети') :
				E('strong', { 'style': 'color:#c62828' }, '● остановлен')),
			row('Сервер', (s.server_name || s.server || '—') + ' (' + (s.active || s.server || '—') + ')' +
				(s.active && s.active !== s.server ? ' — запасной: выбранный «' + s.server + '» не отвечал, вернусь сам' : '')),
			row('Смена серверов', s.failover ? 'сама, если сервер не отвечает 2 минуты' : 'выключена'),
			row('Режим', s.mode === 'tun' && s.devices
				? 'только выбранные устройства (' + s.devices + ') через туннель, остальной дом напрямую' +
				  (s.idle_stop > 0 ? '; туннель поднимается, когда они выходят в интернет' : '')
				: ct.modeName(s.mode) + (s.mode === 'tun' ? ' — ' + s.tun_dev : ' — ' + s.socks)),
			row('Анти-DPI', dpi),
			row('Подписка', s.bundle_age_min < 0 ? 'не скачана' : ('обновлена ' + (s.bundle_age_min < 60 ? s.bundle_age_min + ' мин' : Math.round(s.bundle_age_min / 60) + ' ч') + ' назад') + (s.key ? ', зашифрована' : '')),
			row('Ядро', s.engine || '—'),
			row('Версия', s.update
				? E('span', {}, [ s.version + ' — ', E('strong', {}, 'доступна ' + s.update), ' ',
					E('button', { 'class': 'btn cbi-button-positive', 'click': ui.createHandlerFn(this, () => {
						if (!confirm('Поставить CatTunnel ' + s.update + '? Туннель перезапустится, страница обновится через минуту.')) return;
						return ct.act([ 'upgrade' ]).then((r) => { if (r.code === 0) window.setTimeout(() => location.reload(), 60000); });
					}) }, 'Обновить') ])
				: E('span', {}, [ (s.version || '—') + (s.update_checked > 0 ? ' — последняя (проверено ' + new Date(s.update_checked * 1000).toLocaleString() + ')' : ''), ' ',
					E('button', { 'class': 'btn', 'click': ui.createHandlerFn(this, () =>
						ct.act([ 'upgrade', 'check' ]).then(() => ct.json('status')).then((n) => dom.content(this.box, this.renderTable(n)))) }, 'Проверить') ]))
		]);
	},

	renderDoctor(d) {
		if (!d)
			return E('em', {}, 'проверка не ответила');
		const icon = { ok: '✓ ', info: '• ', warn: '⚠ ' };
		const color = { ok: '#2e7d32', info: 'inherit', warn: '#e65100' };
		const same = d.recommend.mode === d.current.mode && d.recommend.dns === d.current.dns && d.recommend.socks === d.current.socks;
		return E('div', {}, [
			E('ul', {}, d.findings.map((f) => E('li', { 'style': 'color:' + (color[f.level] || 'inherit') }, (icon[f.level] || '') + f.text))),
			d.hints.length ? E('div', {}, [ E('strong', {}, 'Как встроить:'), E('ul', {}, d.hints.map((h) => E('li', {}, h))) ]) : '',
			E('p', {}, 'Рекомендую: режим ' + d.recommend.mode + ', DNS ' + (d.recommend.dns === 'tunnel' ? 'через туннель' : 'роутера') +
				(d.recommend.mode === 'socks' ? ', SOCKS ' + d.recommend.socks : '') +
				(same ? ' — так и настроено.' : ' (сейчас: ' + d.current.mode + ', DNS ' + d.current.dns + ').')),
			d.nikki && d.nikki.present ? E('p', {}, d.nikki.on
				? [ '✓ Встроен в nikki. ', E('button', { 'class': 'btn cbi-button-negative', 'click': ui.createHandlerFn(this, () =>
					ct.act([ 'nikki', 'off' ]).then(() => ct.json('doctor')).then((n) => dom.content(this.doctorBox, this.renderDoctor(n)))) }, 'Убрать из nikki') ]
				: E('button', { 'class': 'btn cbi-button-positive', 'click': ui.createHandlerFn(this, () =>
					ct.act([ 'nikki', 'on' ]).then(() => ct.json('doctor')).then((n) => dom.content(this.doctorBox, this.renderDoctor(n)))) },
					'Встроить в nikki (CatTunnel → ваш VLESS запасным)')) : '',
			same ? '' : E('button', { 'class': 'btn cbi-button-action', 'click': ui.createHandlerFn(this, () =>
				ct.act([ 'doctor', '--apply' ], 'Рекомендации применены, перезапускаю…').then(() => ct.service('restart'))
					.then(() => ct.json('doctor')).then((n) => dom.content(this.doctorBox, this.renderDoctor(n))))
			}, 'Применить рекомендации')
		]);
	},

	render([ s, doc ]) {
		const box = this.box = E('div', {}, this.renderTable(s));
		this.doctorBox = E('div', {}, this.renderDoctor(doc));
		const testOut = E('span', { 'style': 'margin-left:1em' });

		poll.add(() => ct.json('status').then((n) => { dom.content(box, this.renderTable(n)); }), 5);

		return E('div', { 'class': 'cbi-map' }, [
			E('h2', {}, 'CatTunnel'),
			E('div', { 'class': 'cbi-map-descr' }, 'Туннель TrustTunnel на роутере — наш движок с обходом блокировок, серверы из подписки.'),
			E('div', { 'class': 'cbi-section' }, box),
			E('div', { 'class': 'cbi-page-actions', 'style': 'text-align:left' }, [
				E('button', { 'class': 'btn cbi-button-positive', 'click': ui.createHandlerFn(this, () => ct.service('start')) }, 'Запустить'), ' ',
				E('button', { 'class': 'btn cbi-button-negative', 'click': ui.createHandlerFn(this, () => ct.service('stop')) }, 'Остановить'), ' ',
				E('button', { 'class': 'btn cbi-button-action', 'click': ui.createHandlerFn(this, () => ct.service('restart')) }, 'Перезапустить'), ' ',
				E('button', { 'class': 'btn', 'click': ui.createHandlerFn(this, () => {
					testOut.textContent = 'проверяю…';
					return ct.run([ 'test' ]).then((r) => { testOut.textContent = (r.stdout || r.stderr || '').trim(); });
				}) }, 'Проверить интернет через туннель'),
				testOut
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, 'Соседи по роутеру'),
				E('div', { 'class': 'cbi-section-descr' }, 'Другие VPN, прокси и DNS-службы на этом роутере и как CatTunnel встраивается в их схему, не ломая её.'),
				this.doctorBox
			])
		]);
	},

	handleSave: null, handleSaveApply: null, handleReset: null
});
