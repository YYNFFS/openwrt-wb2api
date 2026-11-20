#!/bin/sh
#
# 交叉编译全部架构的 wb2api 二进制，然后打成 ipk（Linux / macOS / CI 用）。
#
# 版本号来源：$PKG_VERSION > 仓库根 .upstream-version > Makefile 里的 PKG_VERSION。
# 输出：prebuilt/wb2api-linux-*（7 个二进制）+ dist/*.ipk（15 架构 × 2 容器 + LuCI 包）
#
# 用法：
#   ./scripts/build-all.sh                 # 编 7 个二进制并打全部 ipk
#   ./scripts/build-all.sh --skip-pack     # 只编二进制
#   PKG_VERSION=1.14.0 ./scripts/build-all.sh
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

SRC="package/workbuddy2api/src"
OUT="$ROOT/prebuilt"
DIST="$ROOT/dist"
SKIP_PACK=0
[ "${1:-}" = "--skip-pack" ] && SKIP_PACK=1

if [ -z "${PKG_VERSION:-}" ]; then
	if [ -f .upstream-version ]; then
		PKG_VERSION=$(cat .upstream-version)
	else
		PKG_VERSION=$(sed -n 's/^PKG_VERSION:=\([0-9][0-9.]*\).*/\1/p' package/workbuddy2api/Makefile | head -1)
	fi
fi
[ -n "$PKG_VERSION" ] || { echo "拿不到版本号，用 PKG_VERSION= 指定" >&2; exit 1; }

echo "== 版本 $PKG_VERSION"
echo "== go $(go version 2>/dev/null || echo '(未找到 go)')"

mkdir -p "$OUT" "$DIST"

build() {
	name="$1"; arch="$2"; shift 2
	echo ">> linux/$arch -> wb2api-linux-$name"
	( cd "$SRC" && env CGO_ENABLED=0 GOOS=linux GOARCH="$arch" GOTOOLCHAIN=auto \
		GOFLAGS=-mod=vendor "$@" \
		go build -trimpath -buildvcs=false \
		-ldflags "-s -w -X main.appVersion=$PKG_VERSION" \
		-o "$OUT/wb2api-linux-$name" ./cmd/server )
}

build mipsle mipsle GOMIPS=softfloat
build mips   mips   GOMIPS=softfloat
build armv7  arm    GOARM=7
build armv6  arm    GOARM=6
build arm64  arm64
build amd64  amd64
build 386    386

echo
echo "== prebuilt"
ls -l "$OUT"

if [ "$SKIP_PACK" = "1" ]; then
	exit 0
fi

# 两种容器都出：tgz = OpenWrt 24.10+，ar = 22.03/23.05（文件名带 -legacy）
PKG_VERSION="$PKG_VERSION" python3 scripts/build-ipk.py --all --format both --out "$DIST"

echo
echo "== dist"
ls -l "$DIST"
