'use strict';
'require view';
'require ui';
'require dom';

/* Справка — как «Помощь» в приложении: «CatTunnel на роутере» (router/help/ROUTER.ru.md) и
 * «Как устроено подключение» (тот же CONNECTION.ru.md, что в приложении: движок общий).
 * Файлы кладёт сборка в resources/cattunnel/help/. Разметка — простой Markdown, без HTML. */

function inline(text) {
	// **жирный**, `код`, [текст](https://…) — всё через узлы DOM, без innerHTML
	const out = [];
	const re = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
	let last = 0, m;
	while ((m = re.exec(text))) {
		if (m.index > last) out.push(text.slice(last, m.index));
		if (m[1]) out.push(E('strong', {}, m[1]));
		else if (m[2]) out.push(E('code', {}, m[2]));
		else out.push(E('a', { 'href': m[4], 'target': '_blank', 'rel': 'noopener noreferrer' }, m[3]));
		last = re.lastIndex;
	}
	if (last < text.length) out.push(text.slice(last));
	return out;
}

function render(md) {
	const nodes = [];
	let list = null, para = null;
	const flush = () => { para = null; list = null; };
	md.split('\n').forEach((raw) => {
		const line = raw.replace(/\s+$/, '');
		let m;
		if (!line.trim()) { flush(); return; }
		if ((m = /^(#{1,3})\s+(.*)$/.exec(line))) {
			flush();
			nodes.push(E([ 'h2', 'h3', 'h4' ][m[1].length - 1], {}, inline(m[2])));
		} else if ((m = /^\s*(?:-|\d+\.)\s+(.*)$/.exec(line))) {
			const ordered = /^\s*\d+\./.test(line);
			if (!list || list.tagName !== (ordered ? 'OL' : 'UL')) { list = E(ordered ? 'ol' : 'ul'); nodes.push(list); }
			list.appendChild(E('li', {}, inline(m[1])));
			para = null;
		} else if (list && /^\s{2,}\S/.test(raw)) {
			// продолжение пункта списка с отступом
			const li = list.lastChild; li.appendChild(E('br')); inline(line.trim()).forEach((n) => li.append(n));
		} else {
			list = null;
			if (!para) { para = E('p'); nodes.push(para); } else para.append(' ');
			inline(line).forEach((n) => para.append(n));
		}
	});
	return nodes;
}

return view.extend({
	load() {
		const get = (name) => fetch(L.resource('cattunnel/help/' + name), { cache: 'no-store' })
			.then((r) => r.ok ? r.text() : '').catch(() => '');
		return Promise.all([ get('ROUTER.ru.md'), get('CONNECTION.ru.md') ]);
	},

	render([ router, connection ]) {
		const body = E('div', { 'class': 'cbi-section help' });
		const show = (md) => dom.content(body, md ? render(md) : E('p', {}, 'Справка не найдена — переустановите пакет CatTunnel.'));
		const tabBtn = (text, md) => E('button', { 'class': 'btn', 'click': (ev) => {
			ev.currentTarget.parentNode.querySelectorAll('button').forEach((b) => b.classList.remove('cbi-button-action'));
			ev.currentTarget.classList.add('cbi-button-action');
			show(md);
		} }, text);
		const first = tabBtn('CatTunnel на роутере', router);
		first.classList.add('cbi-button-action');
		show(router);
		return E('div', { 'class': 'cbi-map' }, [
			E('div', { 'class': 'cbi-page-actions', 'style': 'text-align:left' }, [ first, ' ', tabBtn('Как устроено подключение', connection) ]),
			body
		]);
	},

	handleSave: null, handleSaveApply: null, handleReset: null
});
