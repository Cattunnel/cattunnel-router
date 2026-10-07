'use strict';
'require view';
'require ui';
'require cattunnel.common as ct';

return view.extend({
	render() {
		const out = E('pre', { 'style': 'white-space:pre-wrap;max-height:30em;overflow:auto' }, '');
		const show = (r) => { out.textContent = ((r.stdout || '') + (r.stderr || '')).trim() || '(пусто)'; };
		const btn = (text, args) => E('button', { 'class': 'btn cbi-button-action', 'click': ui.createHandlerFn(this, () => {
			out.textContent = '…';
			return ct.run(args).then(show);
		}) }, text);

		return E('div', { 'class': 'cbi-map' }, [
			E('h2', {}, 'Диагностика'),
			E('div', { 'class': 'cbi-map-descr' }, 'Пароли в журнале скрыты. Кусок для mihomo вставляется в профиль nikki (/etc/nikki/profiles/…).'),
			E('div', { 'class': 'cbi-page-actions', 'style': 'text-align:left' }, [
				btn('Проверить интернет через туннель', [ 'test' ]), ' ',
				btn('Журнал движка', [ 'log', '200' ]), ' ',
				btn('Кусок конфига для mihomo', [ 'mihomo' ])
			]),
			E('div', { 'class': 'cbi-section' }, out)
		]);
	},

	handleSave: null, handleSaveApply: null, handleReset: null
});
