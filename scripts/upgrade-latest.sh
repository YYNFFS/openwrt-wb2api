#!/bin/sh
#
# 在 OpenWrt 路由器上直接跑：从 GitHub Releases 拉最新版并安装。
#
# 用法（路由器上）：
#   sh /tmp/upgrade-latest.sh            # 检查并升级到最新
#   sh /tmp/upgrade-latest.sh --check    # 只看有没有新版，不动系统
#   sh /tmp/upgrade-latest.sh --force    # 版本相同也重装
#
# 环境变量：
#   REPO=YYNFFS/openwrt-wb2api          仓库
#   ASSET_HOST=https://github.com       Releases 资源下载域名（换了 CDN/镜像时用）
#
# 依赖：curl、opkg、sha256sum（busybox 自带）、awk/sed
set -e

REPO=${REPO:-YYNFFS/openwrt-wb2api}
ASSET_HOST=${ASSET_HOST:-https://github.com}
CHECK=0
FORCE=0

for a in "$@"; do
	case "$a" in
	--check) CHECK=1 ;;
	--force) FORCE=1 ;;
	-h | --help)
		sed -n '2,16p' "$0"
		exit 0
		;;
	*)
		echo "未知参数：$a" >&2
		exit 2
		;;
	esac
done

say() { echo "== $*"; }
die() { echo "!! $*" >&2; exit 1; }

# ---------- 设备信息 ----------
[ -f /etc/openwrt_release ] || die "这不是 OpenWrt / ImmortalWrt 系统"
. /etc/openwrt_release
ARCH=${DISTRIB_ARCH:-}
REL=${DISTRIB_RELEASE:-0.0}
[ -n "$ARCH" ] || die "读不到 DISTRIB_ARCH"

MAJ=$(echo "$REL" | sed 's/[^0-9].*//')
MIN=$(echo "$REL" | cut -d. -f2 | sed 's/[^0-9].*//')
MAJ=${MAJ:-0}
MIN=${MIN:-0}
SUF=""
if [ "$MAJ" -lt 24 ] || { [ "$MAJ" -eq 24 ] && [ "$MIN" -lt 10 ]; }; then
	SUF="-legacy"
fi

say "系统 $DISTRIB_ID $REL ($ARCH)，容器格式 $([ -n "$SUF" ] && echo 'ar（22.03/23.05）' || echo 'tar.gz（24.10+）')"

INSTALLED=$(opkg list-installed 2>/dev/null | awk '$1=="workbuddy2api"{print $3}')
LUCI_INSTALLED=$(opkg list-installed 2>/dev/null | awk '$1=="luci-app-workbuddy2api"{print $3}')
# opkg 版本形如 <上游版本>-1，比较时去掉 -<release>
INSTALLED_VER=$(echo "$INSTALLED" | sed 's/-[0-9]*$//')
LUCI_VER=$(echo "$LUCI_INSTALLED" | sed 's/-[0-9]*$//')
say "已装：workbuddy2api=${INSTALLED:-未装}  luci=${LUCI_INSTALLED:-未装}"

# ---------- 查最新版本 ----------
TAG=$(curl -fsSI -o /dev/null -w '%{redirect_url}' "$ASSET_HOST/$REPO/releases/latest" 2>/dev/null | sed 's#.*/tag/##')
if [ -z "$TAG" ]; then
	# 退一步用 API（有 60 次/小时匿名限额）
	TAG=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null |
		sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)
fi
[ -n "$TAG" ] || die "取不到最新版本号（网络不通或被限流），可稍后重试"
VER=${TAG#v}
say "最新：$VER"

if [ "$INSTALLED_VER" = "$VER" ] && [ "$LUCI_VER" = "$VER" ] && [ "$FORCE" != 1 ]; then
	say "已是最新，无需升级"
	exit 0
fi

MAIN="workbuddy2api_${VER}-1_${ARCH}${SUF}.ipk"
LUCI="luci-app-workbuddy2api_${VER}-1_all${SUF}.ipk"
say "将安装：$MAIN"
say "        $LUCI"

if [ "$CHECK" = 1 ]; then
	say "--check 模式，到此为止"
	exit 0
fi

# ---------- 下载 ----------
cd /tmp
for f in "$MAIN" "$LUCI" SHA256SUMS.txt; do
	say "下载 $f"
	curl -fsSL -o "/tmp/$f" "$ASSET_HOST/$REPO/releases/download/$TAG/$f" || die "下载失败：$f"
done

say "校验 SHA256"
for f in "$MAIN" "$LUCI"; do
	want=$(awk -v n="$f" '$2==n{print $1}' /tmp/SHA256SUMS.txt)
	[ -n "$want" ] || die "SHA256SUMS.txt 里没有 $f"
	got=$(sha256sum "/tmp/$f" | awk '{print $1}')
	[ "$want" = "$got" ] || die "$f 校验不符：期望 $want 实得 $got"
	echo "   ok  $f"
done

# ---------- 安装 ----------
say "安装主程序"
opkg install "/tmp/$MAIN" 2>&1 | tail -4
if [ -z "$LUCI_INSTALLED" ]; then
	say "安装 LuCI 界面"
	opkg install "/tmp/$LUCI" 2>&1 | tail -4
elif [ "$LUCI_VER" != "$VER" ]; then
	say "升级 LuCI 界面"
	opkg install "/tmp/$LUCI" 2>&1 | tail -4
else
	say "LuCI 界面已是 $VER，跳过"
fi

rm -f "/tmp/$MAIN" "/tmp/$LUCI" /tmp/SHA256SUMS.txt

# ---------- 验证 ----------
say "重启服务"
/etc/init.d/workbuddy2api restart >/dev/null 2>&1 || true
sleep 3
/etc/init.d/workbuddy2api running && echo "   服务 RUNNING" || echo "   服务 STOPPED"

H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7863/healthz)
P=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7863/panel/)
say "healthz=$H panel=$P"
[ "$H" = "200" ] && [ "$P" = "200" ] || die "升级完成但服务没起来，看 logread -e workbuddy2api"

say "当前版本：$(opkg list-installed 2>/dev/null | awk '$1=="workbuddy2api"{print $3}')"
say "完成"
