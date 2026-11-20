#!/usr/bin/env bash
#
# 把上游 workbuddy2api-panel 的最新 HEAD 同步进本仓库的包内源码，并重算版本号。
#
# 做什么：
#   1. 浅克隆上游（默认 misakano7545/workbuddy2api-panel）
#   2. rsync 覆盖 package/workbuddy2api/src（--delete，删掉上游已移除的文件）
#   3. go mod vendor（OpenWrt SDK 离线编译需要 vendor/）
#   4. 重新生成 files/config.default.json（上游 config.example.json 的 OpenWrt 口径）
#   5. 版本号 = 基础版本 +git<YYYYMMDD>.<sha7>，写进两个 Makefile 与 .upstream-version
#   6. 记录 .upstream-commit / .upstream-date / .upstream-subject 供工作流判断是否变更
#
# 用法：
#   bash scripts/sync-upstream.sh                 # 正常同步
#   UPSTREAM_URL=... bash scripts/sync-upstream.sh
#
# 退出码：0 = 同步完成（不代表有文件变化，变化与否由调用方看 git status）
set -euo pipefail

UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/misakano7545/workbuddy2api-panel.git}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SRC="package/workbuddy2api/src"
MAIN_MK="package/workbuddy2api/Makefile"
LUCI_MK="package/luci-app-workbuddy2api/Makefile"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== 克隆上游 $UPSTREAM_URL"
if [ -n "$UPSTREAM_BRANCH" ]; then
	git clone --quiet --depth 1 --branch "$UPSTREAM_BRANCH" "$UPSTREAM_URL" "$TMP/up"
else
	git clone --quiet --depth 1 "$UPSTREAM_URL" "$TMP/up"
fi

SHA="$(git -C "$TMP/up" rev-parse HEAD)"
SHORT="$(git -C "$TMP/up" rev-parse --short=7 HEAD)"
UDATE="$(git -C "$TMP/up" log -1 --format=%cs)"
SUBJ="$(git -C "$TMP/up" log -1 --format=%s)"
echo "   上游 HEAD = $SHA"
echo "   时间 = $UDATE"
echo "   摘要 = $SUBJ"

echo "== 同步源码 -> $SRC"
mkdir -p "$SRC"
# 排除 git 元数据与 GitHub 模板：包内只需要能编译的东西
rsync -a --delete \
	--exclude '.git/' \
	--exclude '.github/' \
	--exclude '.gitattributes' \
	--exclude '.gitignore' \
	"$TMP/up/" "$SRC/"

echo "== go mod vendor"
(
	cd "$SRC"
	GOFLAGS= GOTOOLCHAIN=auto go mod vendor
)

echo "== 重新生成 config.default.json"
python3 scripts/gen-default-config.py

echo "== 计算版本号"
BASE="$(sed -n 's/^PKG_VERSION:=\([0-9][0-9.]*\).*/\1/p' "$MAIN_MK" | head -1)"
[ -n "$BASE" ] || BASE="1.14.0"
STAMP="${UDATE//-/}"
VERSION="${BASE}+git${STAMP}.${SHORT}"
echo "   基础版本 = $BASE"
echo "   本次版本 = $VERSION"

sed -i "s|^PKG_VERSION:=.*|PKG_VERSION:=${VERSION}|" "$MAIN_MK"
sed -i "s|^PKG_RELEASE:=.*|PKG_RELEASE:=1|" "$MAIN_MK"
sed -i "s|^PKG_VERSION:=.*|PKG_VERSION:=${VERSION}|" "$LUCI_MK"
sed -i "s|^PKG_RELEASE:=.*|PKG_RELEASE:=1|" "$LUCI_MK"

printf '%s\n' "$SHA"   > .upstream-commit
printf '%s\n' "$VERSION" > .upstream-version
printf '%s\n' "$UDATE" > .upstream-date
printf '%s\n' "$SUBJ"  > .upstream-subject

echo "== 结果"
grep -h '^PKG_VERSION:' "$MAIN_MK" "$LUCI_MK" | sed 's/^/   /'
echo "   $(cat .upstream-commit)  $(cat .upstream-date)"
