#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 workbuddy2api / luci-app-workbuddy2api 打包成 OpenWrt 可安装的 .ipk。
不需要 OpenWrt SDK —— 只用预编译二进制 + 包内的脚本/页面。

ipk 结构（opkg / libarchive 兼容）：
    debian-binary      "2.0\\n"
    control.tar.gz     ./control ./postinst ./prerm ./conffiles
    data.tar.gz        ./usr/bin/wb2api ...

用法：
    # 主程序包（按架构）
    python build-ipk.py --arch mipsel_24kc \
        --binary prebuilt/wb2api-linux-mipsle-mipsel_24kc --out dist

    # LuCI 界面包（架构无关，只需打一次）
    python build-ipk.py --only luci --out dist

    # 全部架构一次打完
    python build-ipk.py --all --out dist
"""

import argparse
import gzip
import io
import os
import shutil
import struct
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "package"
MAIN_FILES = PKG_DIR / "workbuddy2api" / "files"
LUCI_ROOT = PKG_DIR / "luci-app-workbuddy2api" / "root"
PREBUILT = ROOT / "prebuilt"

# 版本来源优先级：环境变量 PKG_VERSION > 仓库根 .upstream-version > 下面的兜底值。
# CI（.github/workflows/build.yml）用环境变量注入，自动跟随上游那套用文件记录。
VERFILE = ROOT / ".upstream-version"


def _resolve_version() -> str:
    v = os.environ.get("PKG_VERSION", "").strip()
    if not v and VERFILE.exists():
        v = VERFILE.read_text(encoding="utf-8").strip()
    return v or "1.14.0"


VERSION = _resolve_version()
RELEASE = (os.environ.get("PKG_RELEASE", "").strip() or "1")
MAINTAINER = "YG"
LICENSE = "MIT"
URL = "https://github.com/misakano7545/workbuddy2api-panel"
EPOCH = 1735689600  # 固定时间戳，保证可复现构建

# OpenWrt 架构 -> 预编译二进制文件名
ARCH_MAP = {
    "mipsel_24kc": "wb2api-linux-mipsle",
    "mipsel_74kc": "wb2api-linux-mipsle",
    "mipsel_1004kc": "wb2api-linux-mipsle",
    "mips_24kc": "wb2api-linux-mips",
    "mips_74kc": "wb2api-linux-mips",
    "arm_cortex-a7": "wb2api-linux-armv7",
    "arm_cortex-a7_neon-vfpv4": "wb2api-linux-armv7",
    "arm_cortex-a9": "wb2api-linux-armv7",
    "arm_cortex-a9_vfpv3-d16": "wb2api-linux-armv7",
    "arm_cortex-a5_vfpv4": "wb2api-linux-armv7",
    "arm_arm1176jzf-s_vfp": "wb2api-linux-armv6",
    "aarch64_cortex-a53": "wb2api-linux-arm64",
    "aarch64_generic": "wb2api-linux-arm64",
    "x86_64": "wb2api-linux-amd64",
    "i386_pentium4": "wb2api-linux-386",
}

MAIN_POSTINST = """#!/bin/sh
[ -n "$IPKG_INSTROOT" ] || {
\tchmod 700 /etc/workbuddy2api 2>/dev/null
\t# 自定义 postinst 覆盖了 opkg 的默认流程，uci-defaults 必须自己跑
\tif [ -x /etc/uci-defaults/90-workbuddy2api ]; then
\t\t( unset IPKG_INSTROOT; /etc/uci-defaults/90-workbuddy2api )
\t\trm -f /etc/uci-defaults/90-workbuddy2api
\tfi
\t/etc/init.d/workbuddy2api enable
\t/etc/init.d/workbuddy2api restart >/dev/null 2>&1
}
exit 0
"""

MAIN_PRERM = """#!/bin/sh
[ -n "$IPKG_INSTROOT" ] || {
\t/etc/init.d/workbuddy2api stop >/dev/null 2>&1
\t/etc/init.d/workbuddy2api disable
}
exit 0
"""

LUCI_POSTINST = """#!/bin/sh
[ -n "$IPKG_INSTROOT" ] || {
\trm -f /tmp/luci-indexcache* 2>/dev/null
\t/etc/init.d/rpcd reload >/dev/null 2>&1
}
exit 0
"""


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

# Windows 上 os.chmod 不保留 Unix 权限位，因此显式记录每个文件的目标 mode。
MODE_OVERRIDES = {}


def _key(p: Path) -> str:
    return p.resolve().as_posix()


def put(dst: Path, src: Path, mode: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(src), str(dst))
    os.chmod(str(dst), mode)
    MODE_OVERRIDES[_key(dst)] = mode


def put_text(dst: Path, text: str, mode: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(str(dst), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.chmod(str(dst), mode)
    MODE_OVERRIDES[_key(dst)] = mode


def make_tar_gz(root: Path, extra: dict = None) -> bytes:
    """把目录树打成 ./ 前缀的 tar.gz（root:root，0644/0755）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        def add_dir(arcname: str) -> None:
            ti = tarfile.TarInfo(arcname)
            ti.type = tarfile.DIRTYPE
            ti.mode = 0o755
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            ti.mtime = EPOCH
            tf.addfile(ti)

        if root is not None:
            add_dir("./")
            for dirpath, dirnames, filenames in os.walk(str(root)):
                dirnames.sort()
                filenames.sort()
                rel_dir = os.path.relpath(dirpath, str(root))
                if rel_dir != ".":
                    add_dir("./" + rel_dir.replace(os.sep, "/"))
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, str(root)).replace(os.sep, "/")
                    st = os.stat(full)
                    mode = MODE_OVERRIDES.get(_key(Path(full)))
                    if mode is None:
                        mode = 0o755 if (st.st_mode & 0o111) else 0o644
                    ti = tarfile.TarInfo("./" + rel)
                    ti.size = st.st_size
                    ti.mode = mode
                    ti.uid = ti.gid = 0
                    ti.uname = ti.gname = "root"
                    ti.mtime = EPOCH
                    with open(full, "rb") as fh:
                        tf.addfile(ti, fh)

        for name, (data, mode) in (extra or {}).items():
            ti = tarfile.TarInfo("./" + name)
            raw = data.encode("utf-8")
            ti.size = len(raw)
            ti.mode = mode
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            ti.mtime = EPOCH
            tf.addfile(ti, io.BytesIO(raw))

    return gzip.compress(buf.getvalue(), compresslevel=9, mtime=0)


def write_ar(path: Path, members) -> None:
    """写 ar 归档（GNU 变体，opkg/libarchive 可读）。

    注意：size 字段必须是原始长度，奇数长度在数据之后补一个 '\\n'。
    """
    out = bytearray(b"!<arch>\n")
    for name, data in members:
        header = "{:<16}{:<12}{:<6}{:<6}{:<8}{:<10}`\n".format(
            name + "/", EPOCH, 0, 0, "100644", len(data)
        )
        out += header.encode("ascii")
        out += data
        if len(data) % 2:
            out += b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))


def dir_size_kb(root: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(str(root)):
        for fn in filenames:
            total += os.path.getsize(os.path.join(dirpath, fn))
    return max(1, (total + 1023) // 1024)


def build_control(pkg, version, arch, depends, section, category, description,
                  installed_kb, provides=None, conffiles=None) -> str:
    lines = [
        "Package: %s" % pkg,
        "Version: %s" % version,
        "Depends: %s" % (depends or ""),
        "Provides: %s" % (provides or ""),
        "Source: package/%s" % pkg,
        "SourceName: %s" % pkg,
        "Section: %s" % section,
        "SourceDateEpoch: %d" % EPOCH,
        "Priority: optional",
        "Maintainer: %s" % MAINTAINER,
        "Architecture: %s" % arch,
        "Installed-Size: %d" % installed_kb,
        "License: %s" % LICENSE,
        "URL: %s" % URL,
        "Category: %s" % category,
        "Description: %s" % description.splitlines()[0],
    ]
    for extra in description.splitlines()[1:]:
        lines.append(" %s" % extra.strip())
    return "\n".join(lines) + "\n"


def make_outer_tgz(members) -> bytes:
    """外层 tar.gz 容器（OpenWrt 24.10+ 的 ipk 格式）。

    members: [(name, bytes), ...]，name 需带 './' 前缀。
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for name, data in members:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o644
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            ti.mtime = EPOCH
            tf.addfile(ti, io.BytesIO(data))
    return gzip.compress(buf.getvalue(), compresslevel=9, mtime=0)


def pack_ipk(out_file: Path, control_text: str, scripts: dict, staging: Path,
             conffiles, fmt: str = "tgz") -> None:
    ctl_extra = {"control": (control_text, 0o644)}
    for name, text in scripts.items():
        if text:
            ctl_extra[name] = (text, 0o755)
    if conffiles:
        ctl_extra["conffiles"] = ("\n".join(conffiles) + "\n", 0o644)

    control_tar = make_tar_gz(None, ctl_extra)
    data_tar = make_tar_gz(staging)

    out_file.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "ar":
        # OpenWrt <= 23.05：ar 归档
        write_ar(out_file, [
            ("debian-binary", b"2.0\n"),
            ("control.tar.gz", control_tar),
            ("data.tar.gz", data_tar),
        ])
    else:
        # OpenWrt >= 24.10：tar.gz 容器
        out_file.write_bytes(make_outer_tgz([
            ("./debian-binary", b"2.0\n"),
            ("./data.tar.gz", data_tar),
            ("./control.tar.gz", control_tar),
        ]))


# --------------------------------------------------------------------------
# 两个包
# --------------------------------------------------------------------------

def build_main(arch: str, binary: Path, out_dir: Path, fmt: str = "tgz") -> Path:
    staging = Path(tempfile.mkdtemp(prefix="wb2api-main-"))
    try:
        put(staging / "usr/bin/wb2api", binary, 0o755)
        put(staging / "etc/init.d/workbuddy2api", MAIN_FILES / "workbuddy2api.init", 0o755)
        put(staging / "etc/config/workbuddy2api", MAIN_FILES / "workbuddy2api.config", 0o644)
        put(staging / "etc/workbuddy2api/config.default.json",
            MAIN_FILES / "config.default.json", 0o644)
        put(staging / "etc/uci-defaults/90-workbuddy2api",
            MAIN_FILES / "90-workbuddy2api", 0o755)
        put(staging / "etc/workbuddy2api/zoneinfo/Asia/Shanghai",
            MAIN_FILES / "zoneinfo" / "Asia" / "Shanghai", 0o644)
        (staging / "etc/workbuddy2api/auths").mkdir(parents=True, exist_ok=True)
        (staging / "etc/workbuddy2api/data").mkdir(parents=True, exist_ok=True)

        control = build_control(
            pkg="workbuddy2api",
            version="%s-%s" % (VERSION, RELEASE),
            arch=arch,
            depends="libc",
            provides="wb2api",
            section="net",
            category="Network",
            description="WorkBuddy/CodeBuddy -> OpenAI compatible API gateway with web panel",
            installed_kb=dir_size_kb(staging),
        )

        suffix = "-legacy" if fmt == "ar" else ""
        out = out_dir / ("workbuddy2api_%s-%s_%s%s.ipk" % (VERSION, RELEASE, arch, suffix))
        pack_ipk(out, control,
                 {"postinst": MAIN_POSTINST, "prerm": MAIN_PRERM},
                 staging,
                 ["/etc/config/workbuddy2api",
                  "/etc/workbuddy2api/config.default.json"],
                 fmt=fmt)
        return out
    finally:
        shutil.rmtree(str(staging), ignore_errors=True)


def build_luci(out_dir: Path, fmt: str = "tgz") -> Path:
    staging = Path(tempfile.mkdtemp(prefix="wb2api-luci-"))
    try:
        shutil.copytree(str(LUCI_ROOT), str(staging), dirs_exist_ok=True)
        for dirpath, _, filenames in os.walk(str(staging)):
            for fn in filenames:
                os.chmod(os.path.join(dirpath, fn), 0o644)

        control = build_control(
            pkg="luci-app-workbuddy2api",
            version="%s-%s" % (VERSION, RELEASE),
            arch="all",
            depends="luci-base, workbuddy2api",
            section="luci",
            category="LuCI",
            description="LuCI web interface for WorkBuddy2API (status / settings / accounts / logs)",
            installed_kb=dir_size_kb(staging),
        )

        suffix = "-legacy" if fmt == "ar" else ""
        out = out_dir / ("luci-app-workbuddy2api_%s-%s_all%s.ipk" % (VERSION, RELEASE, suffix))
        pack_ipk(out, control, {"postinst": LUCI_POSTINST}, staging, None, fmt=fmt)
        return out
    finally:
        shutil.rmtree(str(staging), ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build OpenWrt .ipk for workbuddy2api")
    ap.add_argument("--arch", help="OpenWrt 架构名，如 mipsel_24kc / aarch64_cortex-a53 / x86_64")
    ap.add_argument("--binary", help="该架构的 wb2api 二进制路径")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="输出目录")
    ap.add_argument("--only", choices=["main", "luci", "all"], default="main")
    ap.add_argument("--all", action="store_true", help="按 ARCH_MAP 打完所有架构")
    ap.add_argument("--format", choices=["tgz", "ar", "both"], default="tgz",
                    help="tgz = OpenWrt 24.10+ 的 tar.gz 容器（默认）；"
                         "ar = 22.03/23.05 的 ar 归档；both = 两种都出")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    built = []

    if args.all:
        args.only = "all"

    fmts = ["tgz", "ar"] if args.format == "both" else [args.format]

    if args.only in ("main", "all"):
        if args.all:
            for fmt in fmts:
                for arch, binname in ARCH_MAP.items():
                    b = PREBUILT / binname
                    if not b.exists():
                        print("skip %-28s (缺 %s)" % (arch, b.name))
                        continue
                    built.append(build_main(arch, b, out_dir, fmt))
                    print("built %s" % built[-1].name)
        else:
            if not args.arch or not args.binary:
                ap.error("--only main 需要 --arch 与 --binary")
            b = Path(args.binary)
            if not b.exists():
                ap.error("二进制不存在: %s" % b)
            for fmt in fmts:
                built.append(build_main(args.arch, b, out_dir, fmt))
                print("built %s" % built[-1].name)

    if args.only in ("luci", "all"):
        for fmt in fmts:
            built.append(build_luci(out_dir, fmt))
            print("built %s" % built[-1].name)

    for p in built:
        print("%12d  %s" % (p.stat().st_size, p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
