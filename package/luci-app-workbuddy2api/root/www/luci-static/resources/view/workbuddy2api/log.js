'use strict';
'require view';
'require fs';
'require ui';
'require poll';

var INIT = '/etc/init.d/workbuddy2api';

function readLog() {
	return fs.exec('/sbin/logread', [ '-e', 'workbuddy2api' ]).then(function(r) {
		return (r.stdout || '').trim();
	}).catch(function() {
		return '';
	});
}

return view.extend({
	load: function() {
		return readLog();
	},

	render: function(text) {
		var self = this;

		this.autoRefresh = true;

		this.pre = E('pre', {
			'style': 'max-height:65vh;overflow:auto;font-size:12px;line-height:1.45;' +
				'white-space:pre-wrap;word-break:break-all;background:#111;color:#ddd;padding:8px;border-radius:4px'
		}, text || _('（暂无日志）'));

		this.autoBtn = E('button', {
			'class': 'cbi-button cbi-button-reset',
			'click': function(ev) {
				ev.preventDefault();
				self.autoRefresh = !self.autoRefresh;
				ev.target.textContent = _('自动刷新：') + (self.autoRefresh ? _('开') : _('关'));
			}
		}, _('自动刷新：开'));

		var node = E('div', {}, [
			E('h2', {}, _('运行日志')),
			E('div', { 'class': 'cbi-section' }, [
				E('p', { 'class': 'cbi-value-description' },
					_('数据来源：syslog（logread -e workbuddy2api）。服务重启或系统日志轮转后旧记录会消失。')),
				this.pre,
				E('div', { 'class': 'cbi-page-actions', 'style': 'display:flex;gap:8px;flex-wrap:wrap' }, [
					E('button', {
						'class': 'cbi-button cbi-button-action',
						'click': function(ev) {
							ev.preventDefault();
							self.refresh();
						}
					}, _('刷新')),
					this.autoBtn,
					E('button', {
						'class': 'cbi-button cbi-button-action',
						'click': function(ev) {
							ev.preventDefault();
							self.restartService();
						}
					}, _('重启服务'))
				])
			])
		]);

		poll.add(function() {
			if (!self.autoRefresh) return Promise.resolve();
			return readLog().then(function(t) {
				self.pre.textContent = t || _('（暂无日志）');
				self.pre.scrollTop = self.pre.scrollHeight;
			});
		}, 5);

		return node;
	},

	refresh: function() {
		var self = this;
		return readLog().then(function(t) {
			self.pre.textContent = t || _('（暂无日志）');
			self.pre.scrollTop = self.pre.scrollHeight;
		});
	},

	restartService: function() {
		return fs.exec(INIT, [ 'restart' ]).then(function() {
			ui.addNotification(null, E('p', {}, _('服务已重启')), 'info');
		}).catch(function(e) {
			ui.addNotification(null, E('p', {}, _('重启失败：') + e.message), 'danger');
		});
	}
});
