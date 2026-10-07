'use strict';
'require view';
'require ui';
'require dom';
'require cattunnel.common as ct';

const TLS = { chrome: 'Chrome', firefox: 'Firefox', safari: 'Safari', okhttp: 'OkHttp' };
const DPI = { off: 'выключен', '1': '1: OOB-байт + TTL 1', '2': '2: начало с TTL 1', '3': '3: разрыв в имени сервера', auto: 'авто 1 → 2 → 3', custom: 'своя строка' };

/* «в подписке: Chrome, анти-DPI авто, маскировка 8, QUIC выключен» */
function subSummary(sub) {
	const parts = [ TLS[sub.tls] || sub.tls || 'Chrome', 'анти-DPI ' + (sub.dpi === 'custom' ? '«' + sub.desync + '»' : (DPI[sub.dpi] || sub.dpi)) ];
	parts.push(sub.padding && sub.padding !== '0' ? 'маскировка ' + sub.padding + ' кадров' : 'без маскировки');
	parts.push(sub.quic === 'on' ? 'QUIC выключен' : 'QUIC разрешён');
	return parts.join(', ');
}

const KEYS = [ 'tls', 'dpi', 'padding', 'quic' ];

/* откуда берётся каждое значение: своё у сервера > «для всех» (g — ovr_* из status) > подписка;
   «sub» у сервера — явное «как в подписке», это не своё значение */
function source(o, g) {
	if (KEYS.some((k) => o[k] && o[k] !== 'sub')) return 'own';
	return KEYS.some((k) => !o[k] && g['ovr_' + k]) ? 'all' : 'sub';
}

function select(value, options) {
	return E('select', { 'class': 'cbi-input-select' }, options.map(([ v, label ]) =>
		E('option', { 'value': v, 'selected': String(value) === v ? '' : null }, label)));
}

function field(label, input, hint) {
	return E('div', { 'class': 'cbi-value' }, [
		E('label', { 'class': 'cbi-value-title' }, label),
		E('div', { 'class': 'cbi-value-field' }, [ input, hint ? E('div', { 'class': 'cbi-value-description' }, hint) : '' ])
	]);
}

return view.extend({
	load() { return Promise.all([ ct.json('servers'), ct.json('status') ]); },

	refresh() {
		return this.load().then((d) => dom.content(this.box, this.table(d)));
	},

	/* окно «Настройки сервера» — как страница ключа в приложении */
	openSettings(s) {
		/* в подписях — что именно сейчас будет: «как в подписке (Chrome)» */
		const inh = (sub) => [ [ '', 'как для всех серверов' ], [ 'sub', 'как в подписке (' + sub + ')' ] ];
		const o = s.ovr, su = s.sub || {};
		const tls = select(o.tls, inh(TLS[su.tls] || su.tls || 'Chrome').concat(Object.entries(TLS)));
		const dpi = select(o.dpi, inh(su.dpi === 'custom' ? '«' + su.desync + '»' : (DPI[su.dpi] || su.dpi)).concat(Object.entries(DPI)));
		const desync = E('input', { 'type': 'text', 'class': 'cbi-input-text', 'value': o.desync || '', 'placeholder': '-o1+s -d3+s' });
		const desyncRow = field('Своя строка', desync, 'Части -s/-o/-d через пробел, как в ByeDPI. Нельзя -r и -o без -d после него.');
		const pad = select(o.padding, inh(su.padding && su.padding !== '0' ? su.padding + ' кадров' : 'выключена').concat([ [ '0', 'выключена' ], [ '8', '8 первых кадров (обычно)' ], [ '16', '16 кадров' ], [ '32', '32 кадра' ], [ '64', '64 кадра' ] ]));
		const quic = select(o.quic, inh(su.quic === 'on' ? 'выключен' : 'разрешён').concat([ [ 'on', 'выключен (UDP 443 не пропускается)' ], [ 'off', 'разрешён' ] ]));
		const sync = () => { desyncRow.style.display = dpi.value === 'custom' ? '' : 'none'; };
		dpi.addEventListener('change', sync);
		sync();

		const save = () => {
			const v = o.var + '_';
			return ct.run([ 'set',
				v + 'TLS', tls.value, v + 'DPI', dpi.value, v + 'DESYNC', dpi.value === 'custom' ? desync.value.trim() : '',
				v + 'PADDING', pad.value.trim(), v + 'QUIC', quic.value ]).then((r) => {
				if (r.code !== 0)
					return ui.addNotification(null, E('pre', ((r.stdout || '') + (r.stderr || '')).trim()), 'danger');
				ui.hideModal();
				return (s.selected ? ct.service('restart') : Promise.resolve()).then(() => {
					ui.addNotification(null, E('p', 'Сохранено для ' + s.name + (s.selected ? ', туннель перезапущен.' : '.')), 'info');
					return this.refresh();
				});
			});
		};

		ui.showModal('Настройки: ' + s.name, [
			E('p', {}, [ s.address, E('br'), E('small', {}, 'В подписке: ' + subSummary(s.sub)) ]),
			E('div', { 'class': 'cbi-section' }, [
				field('Отпечаток TLS', tls),
				field('Анти-DPI', dpi, 'Сервер работает и так — оставьте «как в подписке». Не подключается — попробуйте «авто».'),
				desyncRow,
				field('Маскировка размеров', pad, 'Первые пакеты соединения у туннеля всегда одного размера — по этому рисунку фильтр может узнать VPN, даже не видя содержимого. Маскировка добавляет в первые кадры случайный мусор, и размеры каждый раз разные. Обычно хватает 8 (так в подписке); больше — почти без пользы.'),
				field('QUIC', quic)
			]),
			E('div', { 'class': 'right' }, [
				E('button', { 'class': 'btn', 'click': ui.hideModal }, 'Отмена'), ' ',
				E('button', { 'class': 'btn cbi-button-positive', 'click': ui.createHandlerFn(this, save) }, 'Сохранить')
			])
		]);
	},

	table([ list, g ]) {
		g = g || {};
		if (!list || !list.length)
			return E('p', {}, 'Серверов нет — сначала подписка («Настройки»).');
		return E('table', { 'class': 'table' }, [
			E('tr', { 'class': 'tr table-titles' }, [
				E('th', { 'class': 'th' }, 'Сервер'), E('th', { 'class': 'th' }, 'Адрес'),
				E('th', { 'class': 'th' }, 'Настройки'), E('th', { 'class': 'th' }, '')
			])
		].concat(list.map((s) => E('tr', { 'class': 'tr' }, [
			E('td', { 'class': 'td' }, s.selected ? E('strong', {}, '★ ' + s.name) : s.name),
			E('td', { 'class': 'td' }, s.address || '—'),
			E('td', { 'class': 'td' }, { own: E('em', {}, 'свои'), all: 'как для всех серверов', sub: 'как в подписке' }[source(s.ovr, g)]),
			E('td', { 'class': 'td right' }, [
				E('button', { 'class': 'btn', 'click': ui.createHandlerFn(this, () => this.openSettings(s)) }, 'Настройки'), ' ',
				s.selected ? E('em', {}, 'выбран') :
					E('button', { 'class': 'btn cbi-button-action', 'click': ui.createHandlerFn(this, () =>
						ct.act([ 'use', s.key ], 'Выбран ' + s.name + ', перезапускаю…')
							.then(() => ct.service('restart'))
							.then(() => this.refresh()))
					}, 'Выбрать')
			])
		]))));
	},

	render(data) {
		this.box = E('div', { 'class': 'cbi-section' }, this.table(data));
		return E('div', { 'class': 'cbi-map' }, [
			E('h2', {}, 'Серверы'),
			E('div', { 'class': 'cbi-map-descr' }, 'Список приходит из подписки и обновляется сам каждые 6 часов. «Настройки» — свой отпечаток, анти-DPI, маскировка и QUIC для этого сервера, поверх подписки.'),
			this.box,
			E('div', { 'class': 'cbi-page-actions', 'style': 'text-align:left' }, [
				E('button', { 'class': 'btn cbi-button-action', 'click': ui.createHandlerFn(this, () =>
					ct.act([ 'update' ]).then(() => this.refresh()))
				}, 'Обновить подписку сейчас')
			])
		]);
	},

	handleSave: null, handleSaveApply: null, handleReset: null
});
