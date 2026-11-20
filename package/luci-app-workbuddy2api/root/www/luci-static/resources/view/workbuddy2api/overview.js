'use strict';
'require view';
'require fs';
'require ui';
'require poll';

var CONF = '/etc/workbuddy2api/config.json';
var AUTH_DIR = '/etc/workbuddy2api/auths';
var INIT = '/etc/init.d/workbuddy2api';

function readConfig() {
	return fs.read(CONF).then(function(s) {
		return JSON.parse(s);
	}).catch(function() {
		return null;
	});
}

function listAccounts() {
	return fs.list(AUTH_DIR).then(function(entries) {
		return entries.filter(function(e) {
			return e.type === 'file' && /\.json$/.test(e.name);
		});
	}).catch(function() {
		return [];
	});
}

function isRunning() {
	return fs.exec(INIT, [ 'running' ]).then(function(r) {
		return r.code === 0;
	}).catch(function() {
		return false;
	});
}

function portOf(cfg) {
	var l = (cfg && cfg.listen) ? cfg.listen : ':7863';
	var i = l.lastIndexOf(':');
	return (i >= 0) ? l.substring(i + 1) : l;
}

function cbiValue(title, node) {
	return E('div', { 'class': 'cbi-value' }, [
		E('label', { 'class': 'cbi-value-title' }, title),
		E('div', { 'class': 'cbi-value-field' }, node)
	]);
}

return view.extend({
	load: function() {
		return Promise.all([ readConfig(), listAccounts(), isRunning() ]);
	},

	render: function(data) {
		var self = this;

		this.cfg = data[0];
		this.accounts = data[1];
		this.running = data[2];

		var port = portOf(this.cfg);
		var panelUrl = window.location.protocol + '//' + window.location.hostname + ':' + port + '/panel/';

		this.statusEl = E('span', { 'style': 'font-weight:bold' }, '');
		this.portEl = E('span', {}, '');
		this.acctEl = E('span', {}, '');

		var btn = function(label, args, cls) {
			return E('button', {
				'class': 'cbi-button ' + (cls || 'cbi-button-action'),
				'click': function(ev) {
					ev.preventDefault();
					self.runInit(args);
				}
			}, label);
		};

		var node = E('div', {}, [
			E('h2', {}, _('WorkBuddy2API')),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, _('服务状态')),
				cbiValue(_('运行状态'), this.statusEl),
				cbiValue(_('监听地址'), this.portEl),
				cbiValue(_('账号数量'), this.acctEl),
				cbiValue(_('管理面板'), E('a', {
					'href': panelUrl,
					'target': '_blank',
					'rel': 'noopener'
				}, panelUrl)),
				E('div', { 'class': 'cbi-page-actions', 'style': 'display:flex;gap:8px;flex-wrap:wrap' }, [
					btn(_('启动'), [ 'start' ], 'cbi-button-apply'),
					btn(_('停止'), [ 'stop' ], 'cbi-button-reset'),
					btn(_('重启'), [ 'restart' ], 'cbi-button-action'),
					btn(_('开机自启'), [ 'enable' ], 'cbi-button-action'),
					btn(_('取消自启'), [ 'disable' ], 'cbi-button-reset')
				])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, _('说明')),
				E('p', {}, _('本服务把 CodeBuddy / WorkBuddy 账号池包装成 OpenAI 兼容接口：')),
				E('pre', { 'style': 'font-size:12px;overflow:auto' },
					'BASE_URL = http://' + window.location.hostname + ':' + port + '/v1\n' +
					'API_KEY  = （见「设置」页的 api_key 字段）'),
				E('p', {}, _('账号的添加、签到任务、用量统计等高级功能，请打开上面的管理面板操作。'))
			])
		]);

		this.updateStatus(this.running);

		poll.add(function() {
			return Promise.all([ isRunning(), listAccounts(), readConfig() ]).then(function(r) {
				self.running = r[0];
				self.accounts = r[1];
				if (r[2]) self.cfg = r[2];
				self.updateStatus(r[0]);
			});
		}, 5);

		return node;
	},

	updateStatus: function(running) {
		if (!this.statusEl) return;
		this.statusEl.textContent = running ? _('运行中') : _('已停止');
		this.statusEl.style.color = running ? '#2e7d32' : '#c62828';
		this.portEl.textContent = (this.cfg && this.cfg.listen) ? this.cfg.listen : '—';
		this.acctEl.textContent = String((this.accounts || []).length);
	},

	runInit: function(args) {
		var self = this;
		return fs.exec(INIT, args).then(function(r) {
			if (r.code !== 0)
				throw new Error(((r.stderr || '') + (r.stdout || '')).trim() || ('exit ' + r.code));
			ui.addNotification(null, E('p', {}, _('已执行：') + args.join(' ')), 'info');
		}).catch(function(e) {
			ui.addNotification(null, E('p', {}, _('操作失败：') + e.message), 'danger');
		}).then(function() {
			return Promise.all([ isRunning(), listAccounts() ]).then(function(r) {
				self.running = r[0];
				self.accounts = r[1];
				self.updateStatus(r[0]);
			});
		});
	}
});
