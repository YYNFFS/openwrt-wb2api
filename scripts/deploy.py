#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 workbuddy2api 的 ipk 部署到 OpenWrt 路由器（SSH + SFTP + opkg）。

用法：
    python deploy.py --password XXX                     # 装 dist/ 里的包（全新安装 / 升级）
    python deploy.py --password XXX --latest            # 从 GitHub 最新 Release 下载再装
    python deploy.py --password XXX --latest --force    # 版本相同也重装
    python deploy.py --password XXX --reinstall         # 先卸载再装（清掉旧 conffiles）
    python deploy.py --password XXX --arch x86_64
    python deploy.py --password XXX --host 192.168.6.1 --user root
"""
import argparse
import io
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
REPO = os.environ.get("REPO", "YYNFFS/openwrt-wb2api")
UA = {"User-Agent": "wb2api-deploy/1.0"}


def run(c, cmd, timeout=180):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    code = out.channel.recv_exit_status()
    if o.strip():
        print(o.rstrip())
    if e.strip():
        print("[stderr] " + e.rstrip())
    return code, o, e


def pick(pattern):
    files = sorted(DIST.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        sys.exit("dist/ 里找不到 %s" % pattern)
    return files[-1]


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def latest_tag():
    """先走 releases/latest 的 302 跳转取 tag（不吃 API 限额），失败再退回 API。"""
    url = "https://github.com/%s/releases/latest" % REPO
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            final = r.geturl()
        tag = final.rstrip("/").rsplit("/tag/", 1)[-1]
        if tag and tag != final:
            return urllib.parse.unquote(tag).lstrip("v")
    except Exception as e:
        print("   [warn] 跳转取版本失败：%s，改用 API" % e)
    data = json.loads(_get("https://api.github.com/repos/%s/releases/latest" % REPO))
    return data["tag_name"].lstrip("v")


def container_suffix(release):
    """24.10+ 用 tar.gz 容器，22.03/23.05 用 ar 容器（文件名带 -legacy）。"""
    try:
        major, minor = (release.split(".") + ["0"])[:2]
        if int(major) < 24 or (int(major) == 24 and int(minor) < 10):
            return "-legacy"
    except ValueError:
        pass
    return ""


def fetch_release(ver, arch, suffix):
    """下载最新 Release 的两个 ipk + SHA256SUMS 到临时目录，返回该目录。"""
    tmp = Path(tempfile.mkdtemp(prefix="wb2api-rel-"))
    names = [
        "workbuddy2api_%s-1_%s%s.ipk" % (ver, arch, suffix),
        "luci-app-workbuddy2api_%s-1_all%s.ipk" % (ver, suffix),
        "SHA256SUMS.txt",
    ]
    for n in names:
        url = "https://github.com/%s/releases/download/v%s/%s" % (REPO, ver, n)
        print("== download %s" % url)
        blob = _get(url)
        (tmp / n).write_bytes(blob)
        print("   %.1f KiB" % (len(blob) / 1024))
    return tmp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.6.1")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", required=True)
    ap.add_argument("--arch", default=None, help="留空则读取设备 DISTRIB_ARCH")
    ap.add_argument("--latest", action="store_true", help="从 GitHub 最新 Release 下载后再装")
    ap.add_argument("--force", action="store_true", help="版本相同也继续装")
    ap.add_argument("--reinstall", action="store_true", help="先 opkg remove 并清理 conffiles")
    ap.add_argument("--skip-luci", action="store_true")
    args = ap.parse_args()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(args.host, 22, args.user, args.password, timeout=15,
              allow_agent=False, look_for_keys=False)
    print("== connected %s" % args.host)

    code, o, _ = run(c, "grep -E 'DISTRIB_(ARCH|RELEASE)' /etc/openwrt_release; "
                        "opkg list-installed 2>/dev/null | awk '$1==\"workbuddy2api\"{print \"INSTALLED=\"$3}'")
    arch = args.arch
    release = "24.10"
    installed = None
    for line in o.splitlines():
        if "DISTRIB_ARCH" in line:
            arch = arch or line.split("=")[1].strip().strip("'\"")
        elif "DISTRIB_RELEASE" in line:
            release = line.split("=")[1].strip().strip("'\"")
        elif line.startswith("INSTALLED="):
            installed = line.split("=", 1)[1].strip()
    if not arch:
        sys.exit("无法确定设备架构，请用 --arch 指定")
    print("== arch: %s   系统版本: %s" % (arch, release))

    global DIST
    if args.latest:
        ver = latest_tag()
        print("== 最新 Release: %s（设备已装 %s）" % (ver, installed or "无"))
        if installed == ver and not args.force:
            print("== 已是最新，退出（要重装加 --force）")
            c.close()
            return 0
        DIST = fetch_release(ver, arch, container_suffix(release))

    main_ipk = pick("workbuddy2api_*_%s*.ipk" % arch)
    luci_ipk = None if args.skip_luci else pick("luci-app-workbuddy2api_*_all*.ipk")
    print("== packages: %s%s" % (main_ipk.name, "" if not luci_ipk else ", " + luci_ipk.name))

    if args.reinstall:
        print("\n== remove old")
        run(c, "opkg remove luci-app-workbuddy2api 2>&1 | tail -2")
        run(c, "opkg remove workbuddy2api 2>&1 | tail -2")
        run(c, "rm -f /etc/workbuddy2api/config.default.json /etc/config/workbuddy2api; "
               "rm -f /etc/uci-defaults/90-workbuddy2api; echo cleaned")

    sftp = c.open_sftp()
    remote = []
    for f in ([main_ipk] if not luci_ipk else [main_ipk, luci_ipk]):
        dst = "/tmp/" + f.name
        t0 = time.time()
        sftp.put(str(f), dst)
        remote.append(dst)
        print("== uploaded %s (%.1f KiB, %.1fs)" % (f.name, f.stat().st_size / 1024, time.time() - t0))
    sftp.close()

    for path in remote:
        print("\n== opkg install %s" % path)
        code, o, e = run(c, "opkg install %s 2>&1" % path, timeout=240)
        print("[exit %d]" % code)

    print("\n== files")
    run(c, "ls -l /usr/bin/wb2api /etc/init.d/workbuddy2api /etc/workbuddy2api/config.json "
           "/etc/workbuddy2api/zoneinfo/Asia/Shanghai 2>&1")

    print("\n== installed version")
    run(c, "opkg list-installed 2>/dev/null | grep -E 'workbuddy2api'")

    print("\n== service")
    run(c, "/etc/init.d/workbuddy2api running && echo RUNNING || echo STOPPED")
    run(c, "pid=$(pgrep -f '[w]b2api' | head -1); echo pid=$pid; "
           "tr '\\0' '\\n' < /proc/$pid/environ | grep -E '^TZ='; "
           "ls -l /proc/$pid/cwd")

    print("\n== api key")
    run(c, "grep -o '\"api_key\": \"[^\"]*\"' /etc/workbuddy2api/config.json; "
           "grep -E '\"(auth_dir|state_file)\"' /etc/workbuddy2api/config.json")

    print("\n== http")
    run(c, "sleep 2; curl -s -o /dev/null -w 'healthz=%{http_code}\\n' http://127.0.0.1:7863/healthz; "
           "curl -s -o /dev/null -w 'panel=%{http_code}\\n' http://127.0.0.1:7863/panel/")

    print("\n== firewall")
    run(c, "uci show firewall | grep -i wb2api")

    print("\n== log (tail)")
    run(c, "logread -e workbuddy2api | tail -8")

    c.close()
    print("\n== done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
