'use strict';
'require view';
'require ui';
'require cattunnel.common as ct';

function select(value, options) {
	return E('select', { 'class': 'cbi-input-select' }, options.map(([ v, label ]) =>
		E('option', { 'value': v, 'selected': String(value) === v ? '' : null }, label)));
}

function text(value, placeholder, type) {
	return E('input', { 'type': type || 'text', 'class': 'cbi-input-text', 'value': value || '', 'placeholder': placeholder || '' });
}

function field(label, input, hint) {
	return E('div', { 'class': 'cbi-value' }, [
		E('label', { 'class': 'cbi-value-title' }, label),
		E('div', { 'class': 'cbi-value-field' }, [ input, hint ? E('div', { 'class': 'cbi-value-description' }, hint) : '' ])
	]);
}

/* set NAME value for each pair, one after another; then restart the tunnel */
function saveAll(pairs, extra) {
	return ct.run([ 'set' ].concat(...pairs)).then((r) => {
		if (r.code !== 0) {
			ui.addNotification(null, E('pre', ((r.stdout || '') + (r.stderr || '')).trim()), 'danger');
			return false;
		}
		return true;
	}).then((ok) => {
		if (!ok) return;
		return (extra ? extra() : Promise.resolve()).then(() => ct.service('restart')).then(() =>
			ui.addNotification(null, E('p', 'Сохранено, туннель перезапущен.'), 'info'));
	});
}

return view.extend({
	load() { return Promise.all([ ct.json('status'), ct.json('leases'), ct.run([ 'web', 'status' ]), ct.json('direct') ]); },

	render([ s, leases, web, direct ]) {
		s = s || {};
		leases = leases || [];

		/* Свои сайты и IP напрямую — как в приложении: по строке */
		const directBox = E('textarea', { 'class': 'cbi-input-textarea', 'rows': 6, 'style': 'width:100%;font-family:monospace',
			'placeholder': 'example.com\n*.example.org\n1.2.3.4\n10.0.0.0/8' }, (direct || []).join('\n'));

		/* Подписка */
		const url = text('', 'https://…/api/ct/…  (можно несколько через « | »)');
		url.style.width = '100%';
		const key = text('', 'AGE-SECRET-KEY-1…', 'password');
		key.setAttribute('autocomplete', 'off');
		key.style.width = '100%';

		/* Режим */
		const mode = select(s.mode || 'socks', [ [ 'socks', 'SOCKS5 — для mihomo / nikki' ], [ 'tun', 'tun — весь LAN через туннель' ] ]);
		const socks = text(s.socks || '127.0.0.1:1080');
		const failover = select(s.failover === false ? 'off' : 'on', [
			[ 'on', 'сама — следующий сервер, если этот не отвечает 2 минуты' ], [ 'off', 'выключена — только выбранный сервер' ] ]);

		/* Защита и сеть */
		const killswitch = select(s.killswitch === false ? 'off' : 'on', [
			[ 'on', 'включён — туннель упал, трафик не уходит напрямую' ], [ 'off', 'выключен — при падении туннеля трафик идёт мимо него' ] ]);
		const ru = select(s.ru_direct === false ? 'off' : 'on', [
			[ 'on', 'напрямую — .ru, .su, .рф и др. мимо туннеля' ], [ 'off', 'тоже через туннель' ] ]);
		const dns = select(s.dns || 'router', [
			[ 'router', 'DNS роутера (как настроен в Сеть → DHCP и DNS)' ], [ 'tunnel', 'через туннель — семейный DNS из подписки (фильтр рекламы)' ] ]);
		const mtu = text(s.mtu || '1350', '1350');

		/* Только эти устройства (tun): MAC или имя из DHCP через пробел; галочки — из списка устройств в сети */
		const devices = text(s.devices || '', 'пусто — весь дом через туннель');
		devices.style.width = '100%';
		const devList = () => devices.value.trim().split(/\s+/).filter((x) => x);
		const devBoxes = leases.map((l) => {
			const id = l.name || l.mac;
			// как в cattunnel: MAC, имя или начало имени со «*» (S22* — телефон с меняющимся MAC)
			const hit = (x) => { x = x.toLowerCase(); if (x.includes(':')) return x === l.mac; if (!l.name) return false;
				const n = l.name.toLowerCase(); return x.endsWith('*') ? n.startsWith(x.slice(0, -1)) : n === x; };
			const on = () => devList().some(hit);
			const cb = E('input', { 'type': 'checkbox', 'checked': on() ? '' : null, 'change': (ev) => {
				let v = devList().filter((x) => !hit(x));
				if (ev.target.checked) v.push(l.name ? l.name : l.mac);
				devices.value = v.join(' ');
			} });
			return E('label', { 'style': 'display:block' }, [ cb, ' ', l.name || '(без имени)', ' — ', l.ip, ' ', E('small', {}, l.mac) ]);
		});

		/* Для экспертов: строка «все серверы» + строка на каждый сервер */
		const TLS = [ [ 'chrome', 'Chrome' ], [ 'firefox', 'Firefox' ], [ 'safari', 'Safari' ], [ 'okhttp', 'OkHttp' ] ];
		const DPI = [ [ 'off', 'выключен' ], [ '1', '1: OOB + TTL 1' ], [ '2', '2: TTL 1' ], [ '3', '3: разрыв в имени' ], [ 'auto', 'авто 1→2→3' ], [ 'custom', 'своя строка' ] ];
		const QUIC = [ [ 'on', 'выключен' ], [ 'off', 'разрешён' ] ];
		const inherit = (all) => all ? [ [ '', 'как в подписке' ] ] : [ [ '', 'как для всех' ], [ 'sub', 'как в подписке' ] ];

		const expertRow = (title, prefix, v, all) => {
			const tls = select(v.tls || '', inherit(all).concat(TLS));
			const dpi = select(v.dpi || '', inherit(all).concat(DPI));
			const desync = text(v.desync || '', '-o1+s -d3+s');
			const pad = select(v.padding || '', inherit(all).concat([ [ '0', 'выключена' ], [ '8', '8 первых кадров (обычно)' ], [ '16', '16 кадров' ], [ '32', '32 кадра' ], [ '64', '64 кадра' ] ]));
			const quic = select(v.quic || '', inherit(all).concat(QUIC));
			const sync = () => { desync.style.display = dpi.value === 'custom' ? '' : 'none'; };
			dpi.addEventListener('change', sync);
			sync();
			return {
				node: E('tr', { 'class': 'tr' }, [
					E('td', { 'class': 'td' }, all ? E('strong', {}, title) : title),
					E('td', { 'class': 'td' }, tls), E('td', { 'class': 'td' }, [ dpi, desync ]),
					E('td', { 'class': 'td' }, pad), E('td', { 'class': 'td' }, quic)
				]),
				pairs: () => [
					[ prefix + 'TLS', tls.value ], [ prefix + 'DPI', dpi.value ],
					[ prefix + 'DESYNC', dpi.value === 'custom' ? desync.value.trim() : '' ],
					[ prefix + 'PADDING', pad.value.trim() ], [ prefix + 'QUIC', quic.value ]
				]
			};
		};
		const rows = [ expertRow('Все серверы', 'OVR_', { tls: s.ovr_tls, dpi: s.ovr_dpi, desync: s.ovr_desync, padding: s.ovr_padding, quic: s.ovr_quic }, true) ];
		const loglevel = select(s.loglevel || 'info', [ [ 'error', 'только ошибки' ], [ 'warn', 'предупреждения' ], [ 'info', 'обычный' ], [ 'debug', 'подробный (для отладки)' ] ]);

		const expert = E('div', { 'style': 'display:none' }, [
			E('div', { 'class': 'cbi-section-descr' },
				'Маскировка размеров: первые пакеты туннеля всегда одного размера, по этому рисунку фильтр может узнать VPN; маскировка добавляет случайный мусор (обычно 8 кадров). ' +
				'Значения для всех серверов сразу, поверх подписки. Свои у отдельного сервера — на странице «Серверы» → «Настройки» (они важнее этих). ' +
				'Менять без нужды не стоит: смена отпечатка во время блокировки может продлить «заморозку» адреса.'),
			E('table', { 'class': 'table' }, [
				E('tr', { 'class': 'tr table-titles' }, [ E('th', { 'class': 'th' }, 'Сервер'), E('th', { 'class': 'th' }, 'Отпечаток TLS'),
					E('th', { 'class': 'th' }, 'Анти-DPI'), E('th', { 'class': 'th' }, 'Маскировка размеров'), E('th', { 'class': 'th' }, 'QUIC') ])
			].concat(rows.map((r) => r.node))),
			field('Журнал движка', loglevel)
		]);
		const expertToggle = E('button', { 'class': 'btn', 'click': (ev) => {
			ev.preventDefault();
			const open = expert.style.display === 'none';
			expert.style.display = open ? '' : 'none';
			ev.target.textContent = open ? 'Скрыть' : 'Показать';
		} }, 'Показать');

		const saveBtn = (label, fn) => E('div', { 'class': 'cbi-page-actions', 'style': 'text-align:left' }, [
			E('button', { 'class': 'btn cbi-button-save', 'click': ui.createHandlerFn(this, fn) }, label) ]);

		return E('div', { 'class': 'cbi-map' }, [
			E('h2', {}, 'Настройки'),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, 'Подписка'),
				E('div', { 'class': 'cbi-section-descr' }, s.subscription
					? 'Подписка уже добавлена' + (s.key ? ' (с ключом)' : '') + '. Чтобы заменить — вставьте новую ссылку и ключ.'
					: 'Ссылка и ключ — те же, что вы вставляли в приложение CatTunnel (их присылает бот).'),
				field('Ссылка подписки', url),
				field('Ключ age', key, 'Хранится только на роутере (/etc/cattunnel, права 600).'),
				saveBtn('Добавить подписку', () => {
					if (!url.value.trim())
						return ui.addNotification(null, E('p', 'Вставьте ссылку'), 'warning');
					return ct.act([ 'import', url.value.trim(), key.value.trim() ])
						.then((r) => { if (r.code === 0) { key.value = ''; return ct.service('restart'); } });
				})
			]),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, 'Режим'),
				field('Как пускать трафик', mode,
					'SOCKS5 — туннель как прокси для mihomo (схема с nikki): mihomo сам решает, что пускать в CatTunnel. ' +
					'tun — весь домашний трафик идёт в туннель, локальные сети — мимо.'),
				field('Адрес SOCKS5', socks, 'Только для SOCKS5. Оставьте 127.0.0.1 — снаружи роутера он не нужен.'),
				field('Смена серверов', failover,
					'Порядок — как в подписке; на запасном раз в 30 минут пробую вернуться на выбранный. Резерв-каскад — последним.'),
				saveBtn('Сохранить и перезапустить', () => saveAll(
					[ [ 'SOCKS', socks.value.trim() || '127.0.0.1:1080' ], [ 'MODE', mode.value ], [ 'FAILOVER', failover.value ] ],
					() => ct.run([ 'firewall', mode.value === 'tun' ? 'on' : 'off' ])))
			]),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, 'Защита и сеть'),
				field('Kill switch', killswitch, 'Выключать только если понимаете зачем: без него при сбое туннеля сайты откроются напрямую, через провайдера.'),
				field('Российские сайты', ru, 'Только для режима tun (в SOCKS5 это решает mihomo). По доменам и по российским сетям (geoip:ru, сам обновляет список раз в 20 часов) — как «Российские сервисы» в приложении.'),
				field('DNS', dns, 'Только для режима tun. «Через туннель» — запросы домашних устройств идут на семейный DNS из подписки и не видны провайдеру; ' +
					'российские зоны (.ru, .su, .рф…) при «Российские сайты: напрямую» — на DNS провайдера. Адреса серверов роутер узнаёт через DNS провайдера.'),
				field('Только эти устройства', E('div', {}, [ devices ].concat(devBoxes.length ? [ E('div', { 'style': 'margin-top:.5em' }, devBoxes) ] : [])),
					'Только для tun. Через туннель пойдут только отмеченные устройства. Устройство с именем отмечается по имени — так телефон с «частным» (меняющимся) MAC останется в списке; можно и начало имени со «*», например S22*. ' +
					'остальной дом — напрямую. Kill switch и DNS через туннель — тоже только для них. Пусто — весь дом.' +
					(s.devices ? ' Сейчас в туннеле: ' + (s.devices_active || 0) + '.' : '')),
				field('MTU туннеля', mtu, 'Только для tun. 1350 подходит почти всем; при PPPoE или мобильном интернете попробуйте 1280.'),
				saveBtn('Сохранить и перезапустить', () => saveAll(
					[ [ 'KILLSWITCH', killswitch.value ], [ 'RU_DIRECT', ru.value ], [ 'DNS', dns.value ], [ 'DEVICES', devList().join(' ') ], [ 'MTU', mtu.value.trim() || '1350' ] ],
					// DNS всего дома через туннель — только когда в туннеле весь дом (с DEVICES — DNS только этих устройств, это делает сам cattunnel)
					() => ct.run([ 'dns', dns.value === 'tunnel' && mode.value === 'tun' && !devList().length ? 'on' : 'off' ])))
			]),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, 'Сайты и IP напрямую'),
				E('div', { 'class': 'cbi-section-descr' }, 'Свой список мимо туннеля, как в приложении: по строке домен (example.com — сам домен, *.example.com — и все поддомены), IP-адрес или сеть (10.0.0.0/8, 2001:db8::/32). ' +
					'Только для режима tun (в SOCKS5 это решает mihomo); работает и вместе со «Только эти устройства». Российские сайты включаются отдельно — в «Защита и сеть».'),
				directBox,
				saveBtn('Сохранить и перезапустить', () => ct.run([ 'direct', 'set', directBox.value.trim() ]).then((r) => {
					if (r.code !== 0)
						return ui.addNotification(null, E('pre', ((r.stdout || '') + (r.stderr || '')).trim()), 'danger');
					return ct.service('restart').then(() => ui.addNotification(null, E('p', (r.stdout || '').split('—')[0].trim() + ', туннель перезапущен.'), 'info'));
				}))
			]),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, [ 'Для экспертов ', expertToggle ]),
				expert,
				saveBtn('Сохранить и перезапустить', () => saveAll(
					[ [ 'LOGLEVEL', loglevel.value ] ].concat(...rows.map((r) => r.pairs()))))
			]),

			this.webSection(s, web)
		]);
	},

	/* Своя страница CatTunnel (lighttpd, только из домашней сети, пароль) — то же, что команда cattunnel web */
	webSection(s, web) {
		const out = ((web && (web.stdout || web.stderr)) || '').trim();
		const on = /работает/.test(out);
		const pw = E('input', { 'type': 'password', 'class': 'cbi-input-text', 'placeholder': 'от 8 символов, без пробелов и «:»', 'autocomplete': 'new-password' });
		const act = (args, ok) => ct.act(args, ok).then(() => location.reload());
		const setPw = () => {
			const v = pw.value;
			if (v.length < 8) { ui.addNotification(null, E('p', 'Пароль — от 8 символов'), 'danger'); return Promise.resolve(); }
			return ct.act([ 'web', 'password', v ]).then((r) => (r.code === 0 && !on) ? act([ 'web', 'on' ]) : location.reload());
		};
		/* На самой отдельной странице — только смена пароля: выключать её отсюда — значит отрезать себе
		   единственный интерфейс (на Keenetic нет LuCI); включить и выключить её можно в LuCI или командой */
		if (window.CT_STANDALONE)
			return E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, 'Пароль этой страницы'),
				E('div', { 'class': 'cbi-section-descr' }, 'Пользователь admin. В роутере хранится только хэш пароля. После смены браузер спросит новый.'),
				field('Новый пароль', pw),
				E('div', { 'class': 'cbi-page-actions', 'style': 'text-align:left' }, [
					E('button', { 'class': 'btn cbi-button-action', 'click': ui.createHandlerFn(this, setPw) }, 'Сменить пароль') ])
			]);
		return E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, 'Отдельная страница CatTunnel'),
			E('div', { 'class': 'cbi-section-descr' }, 'Эти же страницы по отдельному адресу на роутере, без остального интерфейса — удобно дать доступ только к CatTunnel. ' +
				'Открывается только из домашней сети, вход по паролю (пользователь admin), в роутере хранится только хэш пароля. Если обычный порт занят, роутер возьмёт ближайший свободный.'),
			field('Сейчас', E('span', {}, on ? 'включена' : 'выключена')),
			on && (out.match(/https?:\/\/\S+/) || [])[0] ? field('Адрес', E('a', { 'href': out.match(/https?:\/\/\S+/)[0], 'target': '_blank', 'rel': 'noopener' },
				out.match(/https?:\/\/\S+/)[0])) : '',
			field(on ? 'Новый пароль' : 'Пароль', pw),
			E('div', { 'class': 'cbi-page-actions', 'style': 'text-align:left' }, on ? [
				E('button', { 'class': 'btn cbi-button-action', 'click': ui.createHandlerFn(this, setPw) }, 'Сменить пароль'), ' ',
				E('button', { 'class': 'btn cbi-button-negative', 'click': ui.createHandlerFn(this, () => act([ 'web', 'off' ], 'Страница выключена')) }, 'Выключить страницу')
			] : [
				E('button', { 'class': 'btn cbi-button-positive', 'click': ui.createHandlerFn(this, setPw) }, 'Включить страницу')
			])
		]);
	},

	handleSave: null, handleSaveApply: null, handleReset: null
});
