#
# LuCI 界面：服务 -> WorkBuddy2API
#
include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-workbuddy2api
PKG_VERSION:=1.14.0+git20261121.d629a8c
PKG_RELEASE:=1

PKG_LICENSE:=MIT
PKG_MAINTAINER:=YG
PKGARCH:=all

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-workbuddy2api
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=LuCI app for WorkBuddy2API
  PKGARCH:=all
  DEPENDS:=+luci-base +workbuddy2api
endef

define Package/luci-app-workbuddy2api/description
  Web 管理界面：服务启停、监听端口 / API Key、账号列表、
  config.json 在线编辑（保存即生效）、运行日志。
endef

define Build/Compile
endef

define Package/luci-app-workbuddy2api/install
	$(INSTALL_DIR) $(1)/usr/share/luci/menu.d
	$(INSTALL_DATA) ./root/usr/share/luci/menu.d/luci-app-workbuddy2api.json $(1)/usr/share/luci/menu.d/

	$(INSTALL_DIR) $(1)/usr/share/rpcd/acl.d
	$(INSTALL_DATA) ./root/usr/share/rpcd/acl.d/luci-app-workbuddy2api.json $(1)/usr/share/rpcd/acl.d/

	$(INSTALL_DIR) $(1)/www/luci-static/resources/view/workbuddy2api
	$(INSTALL_DATA) ./root/www/luci-static/resources/view/workbuddy2api/overview.js $(1)/www/luci-static/resources/view/workbuddy2api/
	$(INSTALL_DATA) ./root/www/luci-static/resources/view/workbuddy2api/settings.js $(1)/www/luci-static/resources/view/workbuddy2api/
	$(INSTALL_DATA) ./root/www/luci-static/resources/view/workbuddy2api/accounts.js $(1)/www/luci-static/resources/view/workbuddy2api/
	$(INSTALL_DATA) ./root/www/luci-static/resources/view/workbuddy2api/log.js $(1)/www/luci-static/resources/view/workbuddy2api/
endef

define Package/luci-app-workbuddy2api/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	rm -f /tmp/luci-indexcache* 2>/dev/null
	/etc/init.d/rpcd reload >/dev/null 2>&1
}
exit 0
endef

$(eval $(call BuildPackage,luci-app-workbuddy2api))
