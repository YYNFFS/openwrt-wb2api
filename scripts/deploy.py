#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 workbuddy2api 的 ipk 部署到 OpenWrt 路由器（SSH + SFTP + opkg）。

用法：
    python deploy.py --password XXX                     # 全新安装 / 升级
    python deploy.py --password XXX --reinstall         # 先卸载再装（清掉旧 conffiles）
    python deploy.py --password XXX --arch x86_64
"""
import argparse
import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.6.1")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", required=True)
    ap.add_argument("--arch", default=None, help="留空则读取设备 DISTRIB_ARCH")
    ap.add_argument("--reinstall", action="store_true", help="先 opkg remove 并清理 conffiles")
    ap.add_argument("--skip-luci", action="store_true")
    args = ap.parse_args()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(args.host, 22, args.user, args.password, timeout=15,
              allow_agent=False, look_for_keys=False)
    print("== connected %s" % args.host)

    code, o, _ = run(c, "grep -E 'DISTRIB_(ARCH|RELEASE)' /etc/openwrt_release")
    arch = args.arch
    if not arch:
        for line in o.splitlines():
            if "DISTRIB_ARCH" in line:
                arch = line.split("=")[1].strip().strip("'\"")
    if not arch:
        sys.exit("无法确定设备架构，请用 --arch 指定")
    print("== arch: %s" % arch)

    main_ipk = pick("workbuddy2api_*_%s.ipk" % arch)
    luci_ipk = None if args.skip_luci else pick("luci-app-workbuddy2api_*_all.ipk")
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


if __name__ == "__main__":
    sys.exit(main())
