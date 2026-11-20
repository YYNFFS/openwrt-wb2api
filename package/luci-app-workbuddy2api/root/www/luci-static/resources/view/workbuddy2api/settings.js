'use strict';
'require view';
'require fs';
'require ui';
'require uci';

var CONF = '/etc/workbuddy2api/config.json';
var INIT = '/etc/init.d/workbuddy2api';

function input(id, value, type, ph) {
	return E('input', {
		'id': id,
		'class': 'cbi-input-text',
		'type': type || 'text',
		'value': (value === undefined || value === null) ? '' : String(value),
		'placeholder': ph || ''
	});
}

function checkbox(id, checked) {
	return E('input', {
		'id': id,
		'type': 'checkbox',
		'class': 'cbi-input-checkbox',
		'checked': checked ? 'checked' : null
	});
}

function cbiValue(title, node, desc) {
	return E('div', { 'class': 'cbi-value' }, [
		E('label', { 'class': 'cbi-value-title' }, title),
		E('div', { 'class': 'cbi-value-field' }, [
			node,
			desc ? E('div', { 'class': 'cbi-value-description' }, desc) : ''
		])
	]);
}

function randKey() {
	var buf = new Uint8Array(16);
	(window.crypto || window.msCrypto).getRandomValues(buf);
	return Array.prototype.map.call(buf, function(b) {
		return ('0' + b.toString(16)).slice(-2);
	}).join('');
}

function uciBool(v, def) {
	if (v === undefined || v === null) return def;
	return v === '1' || v === 'true' || v === true || v === 'on' || v === 'yes';
}

return view.extend({
	load: function() {
		return Promise.all([
			fs.read(CONF).catch(function() { return '{}'; }),
			uci.load('workbuddy2api')
		]);
	},

	render: function(data) {
		var self = this;

		try {
			this.cfg = JSON.parse(data[0]);
		} catch (e) {
			this.cfg = {};
		}

		var cfg = this.cfg;
		var lg = cfg.logging || {};

		var uEnabled = uciBool(uci.get('workbuddy2api', 'main', 'enabled'), true);
		var uRespawn = uciBool(uci.get('workbuddy2api', 'main', 'respawn'), true);
		var uTz = uci.get('workbuddy2api', 'main', 'zonename') || 'Asia/Shanghai';
		var uExtra = uci.get('workbuddy2api', 'main', 'extra_args') || '';

		var raw = E('textarea', {
			'id': 'wb_raw',
			'rows': 24,
			'wrap': 'off',
			'style': 'width:100%;font-family:monospace;font-size:12px'
		}, JSON.stringify(cfg, null, 2) + '\n');
		this.rawEl = raw;

		var node = E('div', {}, [
			E('h2', {}, _('WorkBuddy2API 设置')),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, _('服务')),
				cbiValue(_('开机自启'), checkbox('wb_enabled', uEnabled)),
				cbiValue(_('异常自动重启'), checkbox('wb_respawn', uRespawn),
					_('由 procd 监管，进程退出后自动拉起')),
				cbiValue(_('进程时区'), input('wb_tz', uTz, 'text', 'Asia/Shanghai'),
					_('IANA 时区名（Go 不解析 POSIX 的 CST-8）。包内自带 Asia/Shanghai；换其它时区需先装 zoneinfo-<region>')),
				cbiValue(_('额外启动参数'), input('wb_extra', uExtra, 'text', '-config /mnt/usb/wb2api.json'),
					_('追加到 /usr/bin/wb2api 命令行末尾，留空即可'))
			]),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, _('网关')),
				cbiValue(_('监听地址'), input('wb_listen', cfg.listen || ':7863', 'text', ':7863'),
					_(':7863 = 监听所有网卡；127.0.0.1:7863 = 只允许本机')),
				cbiValue(_('API Key'), E('div', { 'style': 'display:flex;gap:6px;align-items:center' }, [
					input('wb_key', cfg.api_key || '', 'text'),
					E('button', {
						'class': 'cbi-button cbi-button-action',
						'click': function(ev) {
							ev.preventDefault();
							document.getElementById('wb_key').value = randKey();
						}
					}, _('重新生成'))
				]), _('客户端调用 /v1/* 时携带的 Bearer Token')),
				cbiValue(_('账号目录'), input('wb_auths', cfg.auth_dir || './auths', 'text'),
					_('相对路径以 /etc/workbuddy2api 为基准')),
				cbiValue(_('状态文件'), input('wb_state', cfg.state_file || './data/state.json', 'text'),
					_('账号池状态 / 用量 / 积分历史都放在该文件同目录；写到 /tmp 可减少闪存磨损'))
			]),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, _('请求日志归档')),
				cbiValue(_('启用 JSONL 归档'), checkbox('wb_archive', lg.request_archive_enabled === true),
					_('开启后每次请求写一行到 data/request-logs/，路由器闪存建议关闭')),
				cbiValue(_('保留天数'), input('wb_keep', lg.request_retention_days || 3, 'number')),
				cbiValue(_('容量上限 (MiB)'), input('wb_maxmb', lg.request_archive_max_mb || 16, 'number'))
			]),

			E('div', { 'class': 'cbi-page-actions', 'style': 'display:flex;gap:8px;flex-wrap:wrap' }, [
				E('button', {
					'class': 'cbi-button cbi-button-save',
					'click': ui.createHandlerFn(this, 'saveBasic')
				}, _('保存并重启')),
				E('button', {
					'class': 'cbi-button cbi-button-action',
					'click': ui.createHandlerFn(this, 'reloadFromDisk')
				}, _('重新读取')),
				E('button', {
					'class': 'cbi-button cbi-button-reset',
					'click': ui.createHandlerFn(this, 'restoreDefault')
				}, _('恢复默认配置'))
			]),

			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, _('高级：config.json 原文')),
				E('p', { 'class': 'cbi-value-description' },
					_('完整配置（调度时间、账号池策略、上游超时、Redis 等）。修改后点下面的按钮写入；JSON 必须合法。')),
				raw,
				E('div', { 'class': 'cbi-page-actions' }, [
					E('button', {
						'class': 'cbi-button cbi-button-save',
						'click': ui.createHandlerFn(this, 'saveRaw')
					}, _('保存 JSON 并重启'))
				])
			])
		]);

		return node;
	},

	reloadFromDisk: function() {
		var self = this;
		return fs.read(CONF).then(function(s) {
			self.cfg = JSON.parse(s);
			self.rawEl.value = JSON.stringify(self.cfg, null, 2) + '\n';
			ui.addNotification(null, E('p', {}, _('已重新读取配置，点「保存并重启」前的表单值已刷新为磁盘内容')), 'info');
			window.location.reload();
		}).catch(function(e) {
			ui.addNotification(null, E('p', {}, _('读取失败：') + e.message), 'danger');
		});
	},

	restoreDefault: function() {
		var self = this;
		return fs.read('/etc/workbuddy2api/config.default.json').then(function(s) {
			if (!confirm(_('将用出厂默认配置覆盖当前 config.json，账号文件不受影响。继续？')))
				return;
			return fs.write(CONF, s, 384).then(function() {
				return fs.exec(INIT, [ 'restart' ]);
			}).then(function() {
				ui.addNotification(null, E('p', {}, _('已恢复默认配置并重启')), 'info');
				window.location.reload();
			});
		}).catch(function(e) {
			ui.addNotification(null, E('p', {}, _('恢复失败：') + e.message), 'danger');
		});
	},

	saveBasic: function() {
		var self = this;
		var cfg = this.cfg || {};

		cfg.listen = (document.getElementById('wb_listen').value || '').trim() || ':7863';
		cfg.api_key = (document.getElementById('wb_key').value || '').trim();
		cfg.auth_dir = (document.getElementById('wb_auths').value || '').trim() || './auths';
		cfg.state_file = (document.getElementById('wb_state').value || '').trim() || './data/state.json';

		cfg.logging = cfg.logging || {};
		cfg.logging.request_archive_enabled = document.getElementById('wb_archive').checked;
		cfg.logging.request_retention_days = parseInt(document.getElementById('wb_keep').value, 10) || 3;
		cfg.logging.request_archive_max_mb = parseInt(document.getElementById('wb_maxmb').value, 10) || 16;

		uci.set('workbuddy2api', 'main', 'enabled', document.getElementById('wb_enabled').checked ? '1' : '0');
		uci.set('workbuddy2api', 'main', 'respawn', document.getElementById('wb_respawn').checked ? '1' : '0');
		uci.set('workbuddy2api', 'main', 'zonename', (document.getElementById('wb_tz').value || 'Asia/Shanghai').trim());
		uci.set('workbuddy2api', 'main', 'extra_args', (document.getElementById('wb_extra').value || '').trim());

		return uci.commit('workbuddy2api').then(function() {
			return fs.write(CONF, JSON.stringify(cfg, null, 2) + '\n', 384);
		}).then(function() {
			self.cfg = cfg;
			self.rawEl.value = JSON.stringify(cfg, null, 2) + '\n';
			return fs.exec(INIT, [ 'restart' ]);
		}).then(function(r) {
			if (r && r.code !== 0)
				throw new Error(((r.stderr || '') + (r.stdout || '')).trim() || ('exit ' + r.code));
			ui.addNotification(null, E('p', {}, _('已保存并重启服务')), 'info');
		}).catch(function(e) {
			ui.addNotification(null, E('p', {}, _('保存失败：') + e.message), 'danger');
		});
	},

	saveRaw: function() {
		var self = this;
		var text = this.rawEl.value;
		var obj;

		try {
			obj = JSON.parse(text);
		} catch (e) {
			ui.addNotification(null, E('p', {}, _('JSON 解析失败：') + e.message), 'danger');
			return Promise.resolve();
		}

		return fs.write(CONF, JSON.stringify(obj, null, 2) + '\n', 384).then(function() {
			self.cfg = obj;
			return fs.exec(INIT, [ 'restart' ]);
		}).then(function(r) {
			if (r && r.code !== 0)
				throw new Error(((r.stderr || '') + (r.stdout || '')).trim() || ('exit ' + r.code));
			ui.addNotification(null, E('p', {}, _('JSON 已保存并重启服务')), 'info');
		}).catch(function(e) {
			ui.addNotification(null, E('p', {}, _('保存失败：') + e.message), 'danger');
		});
	}
});
