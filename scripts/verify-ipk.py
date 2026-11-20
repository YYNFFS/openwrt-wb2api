#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ipk 出厂自检：容器格式、control 字段、文件清单与权限、ELF 架构、脚本语法。

用法：
    python scripts/verify-ipk.py                # 校验 dist/ 下全部 ipk
    python scripts/verify-ipk.py dist/xxx.ipk   # 只校验指定文件

检查项：
  1. 容器能被正确识别（ar / tar.gz），两种容器的成员名与 debian-binary 正确
  2. control 里 Package / Version / Architecture / Installed-Size 等字段齐全，
     Architecture 与文件名里的架构一致
  3. data.tar.gz 的清单与权限位符合预期（二进制与 init 脚本 0755，其余 0644）
  4. usr/bin/wb2api 的 ELF e_machine / data 端序 / class 与架构名匹配
  5. postinst / prerm 通过 sh -n 语法检查（无 sh 时跳过并提示）
"""

import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

EM = {
    "mips": 8,
    "arm": 40,
    "aarch64": 183,
    "x86_64": 62,
    "386": 3,
}

EXPECTED_MACHINE = {
    "mipsel_24kc": ("mips", 1, 1),
    "mipsel_74kc": ("mips", 1, 1),
    "mipsel_1004kc": ("mips", 1, 1),
    "mips_24kc": ("mips", 2, 1),
    "mips_74kc": ("mips", 2, 1),
    "arm_cortex-a7": ("arm", 1, 1),
    "arm_cortex-a7_neon-vfpv4": ("arm", 1, 1),
    "arm_cortex-a9": ("arm", 1, 1),
    "arm_cortex-a9_vfpv3-d16": ("arm", 1, 1),
    "arm_cortex-a5_vfpv4": ("arm", 1, 1),
    "arm_arm1176jzf-s_vfp": ("arm", 1, 1),
    "aarch64_cortex-a53": ("aarch64", 1, 2),
    "aarch64_generic": ("aarch64", 1, 2),
    "x86_64": ("x86_64", 1, 2),
    "i386_pentium4": ("386", 1, 1),
}

errors = []
notes = []


def fail(msg):
    errors.append(msg)
    print("  [FAIL] %s" % msg)


def ok(msg):
    print("  [ok]   %s" % msg)


def read_members(path: Path):
    """返回 ({name: bytes}, container) —— 兼容 ar 与 tar.gz 两种 ipk 容器。"""
    head = path.read_bytes()[:8]
    if head.startswith(b"!<arch>"):
        return read_ar(path), "ar"
    if head[:2] == b"\x1f\x8b":
        return read_tgz(path.read_bytes()), "tar.gz"
    raise ValueError("既不是 ar 也不是 tar.gz：%s" % path.name)


def read_tgz(data):
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for ti in tf.getmembers():
            if ti.isfile():
                out[ti.name.lstrip("./")] = tf.extractfile(ti).read()
    return out


def read_ar(path: Path):
    raw = path.read_bytes()
    assert raw.startswith(b"!<arch>\n")
    pos = 8
    out = {}
    while pos + 60 <= len(raw):
        header = raw[pos:pos + 60]
        name = header[0:16].decode("ascii", "replace").strip().rstrip("/")
        size = int(header[48:58].decode("ascii").strip())
        data = raw[pos + 60:pos + 60 + size]
        out[name] = data
        pos += 60 + size + (size % 2)
    return out


def parse_control(text: bytes):
    d = {}
    key = None
    for line in text.decode("utf-8", "replace").splitlines():
        if line.startswith(" "):
            d[key] += "\n" + line.strip()
        elif ": " in line:
            key, val = line.split(": ", 1)
            d[key] = val
    return d


def data_listing(members):
    """返回 data.tar.gz 内的 {path: (mode, size, bytes)}。"""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(members["data.tar.gz"]), mode="r:gz") as tf:
        for ti in tf.getmembers():
            if ti.isfile():
                out[ti.name.lstrip("./")] = (ti.mode, ti.size, tf.extractfile(ti).read())
    return out


def elf_info(blob: bytes):
    if blob[:4] != b"\x7fELF":
        return None
    cls = blob[4]
    data = blob[5]
    machine = int.from_bytes(blob[18:20], "little" if data == 1 else "big")
    return {"class": cls, "data": data, "machine": machine}


def sh_syntax(text: bytes):
    sh = shutil.which("sh") or shutil.which("bash")
    if not sh:
        return None
    with tempfile.NamedTemporaryFile("wb", suffix=".sh", delete=False) as fh:
        fh.write(text)
        tmp = fh.name
    try:
        p = subprocess.run([sh, "-n", tmp], capture_output=True)
        return p.returncode == 0, p.stderr.decode("utf-8", "replace").strip()
    finally:
        os.unlink(tmp)


def check_main(path: Path):
    import re
    m = re.match(r"^workbuddy2api_([0-9.]+)-([0-9]+)_(.+)$", path.stem)
    if not m:
        fail("文件名不符合 workbuddy2api_<ver>-<rel>_<arch>.ipk：%s" % path.name)
        return
    ver, rel, arch = m.groups()
    legacy = arch.endswith("-legacy")
    if legacy:
        arch = arch[: -len("-legacy")]
    if "%s-%s" % (ver, rel) != "1.14.0-1":
        fail("文件名版本 = %s-%s" % (ver, rel))

    print("\n== %s  (%s)" % (path.name, arch))
    members, container = read_members(path)

    want = "ar" if legacy else "tar.gz"
    if container == want:
        ok("容器 = %s" % container)
    else:
        fail("容器 = %s，应为 %s" % (container, want))

    if "debian-binary" not in members or members["debian-binary"] != b"2.0\n":
        fail("debian-binary 缺失或内容不对")
    if "control.tar.gz" not in members or "data.tar.gz" not in members:
        fail("缺 control.tar.gz / data.tar.gz")
        return

    ctl_members = read_tgz(members["control.tar.gz"])
    ctl = parse_control(ctl_members["control"])
    if ctl.get("Package") != "workbuddy2api":
        fail("Package = %r" % ctl.get("Package"))
    if ctl.get("Version") != "1.14.0-1":
        fail("Version = %r" % ctl.get("Version"))
    if ctl.get("Architecture") != arch:
        fail("Architecture = %r，文件名是 %r" % (ctl.get("Architecture"), arch))
    for k in ("Depends", "Installed-Size", "License", "URL", "Section"):
        if not ctl.get(k):
            fail("control 缺字段 %s" % k)

    cf = ctl_members.get("conffiles", b"").decode().split()
    for want_cf in ("/etc/config/workbuddy2api", "/etc/workbuddy2api/config.default.json"):
        if want_cf not in cf:
            fail("conffiles 缺 %s" % want_cf)

    for script in ("postinst", "prerm"):
        if script not in ctl_members:
            fail("缺 %s" % script)
            continue
        res = sh_syntax(ctl_members[script])
        if res is None:
            notes.append("没找到 sh，跳过 %s 语法检查" % script)
        elif res[0]:
            ok("%s 语法通过" % script)
        else:
            fail("%s 语法错误: %s" % (script, res[1]))

    files = data_listing(members)
    required = {
        "usr/bin/wb2api": 0o755,
        "etc/init.d/workbuddy2api": 0o755,
        "etc/uci-defaults/90-workbuddy2api": 0o755,
        "etc/config/workbuddy2api": 0o644,
        "etc/workbuddy2api/config.default.json": 0o644,
        "etc/workbuddy2api/zoneinfo/Asia/Shanghai": 0o644,
    }
    for p, mode in required.items():
        if p not in files:
            fail("data 缺 %s" % p)
            continue
        got = files[p][0] & 0o777
        if got != mode:
            fail("%s 权限 %o，应为 %o" % (p, got, mode))

    binblob = files.get("usr/bin/wb2api", (0, 0, b""))[2]
    info = elf_info(binblob)
    if not info:
        fail("usr/bin/wb2api 不是 ELF")
    else:
        exp = EXPECTED_MACHINE.get(arch)
        if exp:
            key, endian, cls = exp
            if (info["machine"], info["data"], info["class"]) != (EM[key], endian, cls):
                fail("ELF 不符：machine=%d endian=%d class=%d，期望 %s endian=%d class=%d"
                     % (info["machine"], info["data"], info["class"], key, endian, cls))
            else:
                ok("ELF 架构正确（%s）" % key)
        if b"1.14.0" not in binblob:
            fail("二进制里没有 1.14.0 版本串")

    cj = files.get("etc/workbuddy2api/config.default.json", (0, 0, b""))[2]
    if cj:
        import json
        try:
            cfg = json.loads(cj.decode("utf-8"))
            if cfg.get("listen") != "0.0.0.0:7863":
                fail("config.default listen = %r" % cfg.get("listen"))
            if cfg.get("auth_dir") != "/etc/workbuddy2api/auths":
                fail("config.default auth_dir = %r" % cfg.get("auth_dir"))
            if cfg.get("logging", {}).get("request_archive_enabled") is not False:
                fail("config.default 请求归档没关")
            else:
                ok("config.default 覆盖项正确（%d 个顶层段）" % len(cfg))
        except Exception as exc:  # noqa: BLE001
            fail("config.default.json 解析失败: %s" % exc)

    total = sum(v[1] for v in files.values())
    print("  文件 %d 个，解包 %d KiB，Installed-Size %s KiB"
          % (len(files), total // 1024, ctl.get("Installed-Size")))


def check_luci(path: Path):
    name = path.stem
    legacy = name.endswith("-legacy")
    print("\n== %s" % path.name)
    members, container = read_members(path)
    want = "ar" if legacy else "tar.gz"
    if container != want:
        fail("容器 = %s，应为 %s" % (container, want))
    else:
        ok("容器 = %s" % container)

    ctl = parse_control(read_tgz(members["control.tar.gz"])["control"])
    if ctl.get("Package") != "luci-app-workbuddy2api":
        fail("Package = %r" % ctl.get("Package"))
    if ctl.get("Architecture") != "all":
        fail("Architecture = %r" % ctl.get("Architecture"))
    if "workbuddy2api" not in ctl.get("Depends", ""):
        fail("Depends 没依赖主程序包")

    files = data_listing(members)
    need = [
        "usr/share/luci/menu.d/luci-app-workbuddy2api.json",
        "usr/share/rpcd/acl.d/luci-app-workbuddy2api.json",
        "www/luci-static/resources/view/workbuddy2api/overview.js",
        "www/luci-static/resources/view/workbuddy2api/settings.js",
        "www/luci-static/resources/view/workbuddy2api/accounts.js",
        "www/luci-static/resources/view/workbuddy2api/log.js",
    ]
    for p in need:
        if p not in files:
            fail("缺 %s" % p)
    s = files.get("www/luci-static/resources/view/workbuddy2api/settings.js", (0, 0, b""))[2]
    if b"zonename" not in s:
        fail("settings.js 没写 zonename（时区项对不上 init 脚本）")
    else:
        ok("LuCI 文件齐全（%d 个）" % len(files))


def main() -> int:
    if len(sys.argv) > 1:
        targets = [Path(a) for a in sys.argv[1:]]
    else:
        targets = sorted(DIST.glob("*.ipk"))

    if not targets:
        print("没有找到 ipk")
        return 1

    for p in targets:
        if p.name.startswith("luci-app"):
            check_luci(p)
        else:
            check_main(p)

    print("\n==== 汇总 ====")
    print("校验 %d 个包" % len(targets))
    for n in notes:
        print("  [note] %s" % n)
    if errors:
        print("失败 %d 项：" % len(errors))
        for e in errors:
            print("  - %s" % e)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
