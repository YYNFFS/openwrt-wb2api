#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测目标 OpenWrt 路由器的架构、版本、可用空间与传输能力。"""
import sys
import paramiko

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.6.1"
USER = sys.argv[2] if len(sys.argv) > 2 else "root"
PASS = sys.argv[3] if len(sys.argv) > 3 else ""
if not PASS:
    sys.exit("usage: probe-router.py [host] [user] <password>")

CMDS = [
    ("model", "cat /tmp/sysinfo/model 2>/dev/null; cat /proc/device-tree/model 2>/dev/null"),
    ("kernel", "uname -a"),
    ("release", "cat /etc/openwrt_release 2>/dev/null"),
    ("arch", "opkg print-architecture 2>/dev/null"),
    ("pkgarch", "cat /etc/opkg.conf 2>/dev/null; cat /etc/opkg/distfeeds.conf 2>/dev/null | head -3"),
    ("luci", "opkg list-installed 2>/dev/null | grep -E '^luci-base|^libustream|^uhttpd' "),
    ("mem", "free -m 2>/dev/null || cat /proc/meminfo | head -3"),
    ("disk", "df -h / /tmp /overlay 2>/dev/null"),
    ("sftp", "ls -l /usr/libexec/sftp-server /usr/lib/sftp-server /usr/lib/openssh/sftp-server 2>/dev/null; which sftp-server 2>/dev/null"),
    ("tools", "which wget curl tar gzip uci opkg 2>/dev/null"),
    ("svc", "ls /etc/init.d/ | head -40"),
    ("existing", "ls -l /etc/config/workbuddy2api /usr/bin/wb2api /etc/workbuddy2api 2>/dev/null; echo rc=$?"),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=22, username=USER, password=PASS, timeout=15,
              allow_agent=False, look_for_keys=False)
    print("connected to %s" % HOST)
    for name, cmd in CMDS:
        _, out, err = c.exec_command(cmd, timeout=25)
        o = out.read().decode("utf-8", "replace").strip()
        e = err.read().decode("utf-8", "replace").strip()
        print("\n===== %s =====" % name)
        if o:
            print(o)
        if e:
            print("[stderr] " + e)
    c.close()


if __name__ == "__main__":
    sys.exit(main())
