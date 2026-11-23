#
# WorkBuddy2API —— 把 CodeBuddy/WorkBuddy 账号变成 OpenAI 兼容 API 的多账号网关
# OpenWrt 包定义（源码随包提供，SDK 内离线编译；dist/ 下是预编译 ipk）
#
# 用法（OpenWrt SDK / buildroot 根目录）：
#   ./scripts/feeds update packages && ./scripts/feeds install golang
#   cp -r openwrt-wb2api/package/* package/
#   make menuconfig      # Network -> Web Servers/Proxies -> workbuddy2api
#   make package/workbuddy2api/compile V=s
#
# 依赖 feeds/packages/lang/golang 提供的 golang（>= 1.26，上游 go.mod 要求；
# 24.10 自带的是 1.22/1.23，走 SDK 编译需自行升级 golang 包）。
# 只想在路由器上装：直接用 dist/ 下对应架构的预编译 ipk。
#

include $(TOPDIR)/rules.mk

PKG_NAME:=workbuddy2api
PKG_VERSION:=1.15.0+git20261123.d221c72
PKG_RELEASE:=1

PKG_LICENSE:=MIT
PKG_LICENSE_FILES:=LICENSE
PKG_MAINTAINER:=YG

PKG_BUILD_DEPENDS:=golang/host
PKG_BUILD_PARALLEL:=1
PKG_USE_MIPS16:=0
PKG_BUILD_FLAGS:=no-mips16

GO_PKG:=github.com/misakano7545/workbuddy2api-panel
GO_PKG_BUILD_PKG:=./cmd/server
GO_PKG_BUILD_FLAGS:=-trimpath -buildvcs=false -mod=vendor
GO_PKG_LDFLAGS:=-s -w -X main.appVersion=$(PKG_VERSION)

GOLANG_PKG_MK:=$(TOPDIR)/feeds/packages/lang/golang/golang-package.mk

include $(INCLUDE_DIR)/package.mk

ifeq ($(wildcard $(GOLANG_PKG_MK)),)
  $(error 缺少 $(GOLANG_PKG_MK)：请先执行 ./scripts/feeds update packages && ./scripts/feeds install golang)
endif
include $(GOLANG_PKG_MK)

PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_VERSION)

define Package/workbuddy2api
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=Web Servers/Proxies
  TITLE:=WorkBuddy/CodeBuddy -> OpenAI compatible API gateway (with web panel)
  URL:=https://github.com/misakano7545/workbuddy2api-panel
  DEPENDS:=$(GO_ARCH_DEPENDS)
  PROVIDES:=wb2api
endef

define Package/workbuddy2api/description
  Self-hosted OpenAI-compatible reverse proxy for CodeBuddy/WorkBuddy accounts.
  Multi-account pool with weighted scheduling, cooldown/breaker, session
  stickiness, scheduled check-in / keep-alive tasks, SSE streaming and a
  built-in web management panel at /panel/.
endef

define Package/workbuddy2api/conffiles
/etc/config/workbuddy2api
/etc/workbuddy2api/config.default.json
endef

define Build/Prepare
	rm -rf $(PKG_BUILD_DIR)
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) $(CURDIR)/src/. $(PKG_BUILD_DIR)/
endef

define Build/Compile
	( cd $(PKG_BUILD_DIR) && \
		$(GO_PKG_TARGET_VARS) \
		GOCACHE=$(PKG_BUILD_DIR)/.gocache \
		$(STAGING_DIR_HOSTPKG)/bin/go build \
			$(GO_PKG_BUILD_FLAGS) \
			-ldflags "$(GO_PKG_LDFLAGS)" \
			-o server ./cmd/server )
endef

define Package/workbuddy2api/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/server $(1)/usr/bin/wb2api

	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./files/workbuddy2api.init $(1)/etc/init.d/workbuddy2api

	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) ./files/workbuddy2api.config $(1)/etc/config/workbuddy2api

	$(INSTALL_DIR) $(1)/etc/workbuddy2api/auths
	$(INSTALL_DIR) $(1)/etc/workbuddy2api/data
	$(INSTALL_CONF) ./files/config.default.json $(1)/etc/workbuddy2api/config.default.json
	$(INSTALL_DIR) $(1)/etc/workbuddy2api/zoneinfo/Asia
	$(INSTALL_DATA) ./files/zoneinfo/Asia/Shanghai $(1)/etc/workbuddy2api/zoneinfo/Asia/Shanghai

	$(INSTALL_DIR) $(1)/etc/uci-defaults
	$(INSTALL_BIN) ./files/90-workbuddy2api $(1)/etc/uci-defaults/90-workbuddy2api

	$(INSTALL_DIR) $(1)/usr/share/wb2api
endef

define Package/workbuddy2api/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	chmod 700 /etc/workbuddy2api 2>/dev/null
	# 自定义 postinst 会覆盖 opkg 的默认流程，uci-defaults 必须自己跑
	if [ -x /etc/uci-defaults/90-workbuddy2api ]; then
		( unset IPKG_INSTROOT; /etc/uci-defaults/90-workbuddy2api )
		rm -f /etc/uci-defaults/90-workbuddy2api
	fi
	/etc/init.d/workbuddy2api enable
	/etc/init.d/workbuddy2api restart >/dev/null 2>&1
}
exit 0
endef

define Package/workbuddy2api/prerm
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	/etc/init.d/workbuddy2api stop >/dev/null 2>&1
	/etc/init.d/workbuddy2api disable
}
exit 0
endef

$(eval $(call BuildPackage,workbuddy2api))
