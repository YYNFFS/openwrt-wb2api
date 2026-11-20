'use strict';
'require view';
'require fs';
'require ui';
'require poll';

var AUTH_DIR = '/etc/workbuddy2api/auths';
var INIT = '/etc/init.d/workbuddy2api';

function fmtSize(n) {
	if (n === undefined || n === null) return '—';
	if (n < 1024) return n + ' B';
	if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KiB';
	return (n / 1024 / 1024).toFixed(2) + ' MiB';
}

function fmtTime(t) {
	if (!t) return '—';
	try {
		return new Date(t * 1000).toLocaleString();
	} catch (e) {
		return '—';
	}
}

function listAccounts() {
	return fs.list(AUTH_DIR).then(function(entries) {
		return entries.filter(function(e) {
			return e.type === 'file' && /\.json$/.test(e.name);
		}).sort(function(a, b) {
			return a.name.localeCompare(b.name);
		});
	}).catch(function() {
		return [];
	});
}

return view.extend({
	load: function() {
		return listAccounts();
	},

	render: function(entries) {
		var self = this;
		this.entries = entries;

		this.countEl = E('strong', {}, String(entries.length));
		this.tbody = E('tbody', {});

		this.renderRows(entries);

		var node = E('div', {}, [
			E('h2', {}, _('账号')),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, _('凭证文件')),
				E('p', {}, [
					_('共 '), this.countEl, _(' 个账号，存放于 '),
					E('code', {}, AUTH_DIR)
				]),
				E('table', { 'class': 'table' }, [
					E('thead', {}, [
						E('tr', { 'class': 'tr table-titles' }, [
							E('th', { 'class': 'th' }, _('文件')),
							E('th', { 'class': 'th' }, _('大小')),
							E('th', { 'class': 'th' }, _('修改时间')),
							E('th', { 'class': 'th' }, _('操作'))
						])
					]),
					this.tbody
				]),
				E('div', { 'class': 'cbi-page-actions', 'style': 'display:flex;gap:8px;flex-wrap:wrap' }, [
					E('button', {
						'class': 'cbi-button cbi-button-action',
						'click': ui.createHandlerFn(this, 'reloadService')
					}, _('重新加载账号')),
					E('button', {
						'class': 'cbi-button cbi-button-action',
						'click': ui.createHandlerFn(this, 'refreshList')
					}, _('刷新列表'))
				])
			]),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, _('添加账号')),
				E('p', {}, _('推荐走网关自带面板的 OAuth 设备授权流程（浏览器登录，自动落盘凭证）：')),
				E('ol', {}, [
					E('li', {}, _('打开管理面板 → 「账号」→「添加账号」')),
					E('li', {}, _('按提示在浏览器完成 CodeBuddy / WorkBuddy 登录授权')),
					E('li', {}, _('凭证会写入上面的目录，返回本页点「重新加载账号」'))
				]),
				E('p', { 'class': 'cbi-value-description' },
					_('也可以把已有的 workbuddy-*.json 凭证文件直接上传到该目录（SCP / WinSCP）。'))
			])
		]);

		poll.add(function() {
			return listAccounts().then(function(list) {
				self.entries = list;
				self.countEl.textContent = String(list.length);
				self.renderRows(list);
			});
		}, 15);

		return node;
	},

	renderRows: function(entries) {
		var self = this;

		while (this.tbody.firstChild)
			this.tbody.removeChild(this.tbody.firstChild);

		if (!entries.length) {
			this.tbody.appendChild(E('tr', { 'class': 'tr' }, [
				E('td', { 'class': 'td', 'colspan': 4 }, _('（暂无账号）'))
			]));
			return;
		}

		entries.forEach(function(e) {
			self.tbody.appendChild(E('tr', { 'class': 'tr' }, [
				E('td', { 'class': 'td' }, E('code', {}, e.name)),
				E('td', { 'class': 'td' }, fmtSize(e.size)),
				E('td', { 'class': 'td' }, fmtTime(e.mtime)),
				E('td', { 'class': 'td' }, [
					E('button', {
						'class': 'cbi-button cbi-button-remove',
						'click': function(ev) {
							ev.preventDefault();
							self.removeAccount(e.name);
						}
					}, _('删除'))
				])
			]));
		});
	},

	removeAccount: function(name) {
		var self = this;

		if (!confirm(_('删除账号凭证 ') + name + _(' ？删除后需重新登录授权。')))
			return Promise.resolve();

		return fs.remove(AUTH_DIR + '/' + name).then(function() {
			return fs.exec(INIT, [ 'restart' ]);
		}).then(function() {
			ui.addNotification(null, E('p', {}, _('已删除 ') + name + _(' 并重启服务')), 'info');
			return self.refreshList();
		}).catch(function(e) {
			ui.addNotification(null, E('p', {}, _('删除失败：') + e.message), 'danger');
		});
	},

	reloadService: function() {
		return fs.exec(INIT, [ 'restart' ]).then(function(r) {
			if (r && r.code !== 0)
				throw new Error(((r.stderr || '') + (r.stdout || '')).trim() || ('exit ' + r.code));
			ui.addNotification(null, E('p', {}, _('服务已重启，账号池已重新加载')), 'info');
		}).catch(function(e) {
			ui.addNotification(null, E('p', {}, _('重启失败：') + e.message), 'danger');
		});
	},

	refreshList: function() {
		var self = this;
		return listAccounts().then(function(list) {
			self.entries = list;
			self.countEl.textContent = String(list.length);
			self.renderRows(list);
		});
	}
});
