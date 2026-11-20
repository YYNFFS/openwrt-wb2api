#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断已安装的 workbuddy2api 服务。"""
import sys
import paramiko

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.6.1"
USER = sys.argv[2] if len(sys.argv) > 2 else "root"
PASS = sys.argv[3] if len(sys.argv) > 3 else ""
if not PASS:
    sys.exit("usage: diag.py [host] [user] <password>")

CMDS = [
    ("uci-defaults 残留", "ls -l /etc/uci-defaults/ 2>/dev/null"),
    ("进程环境", "pid=$(pgrep -f '[w]b2api' | head -1); echo pid=$pid; "
                 "tr '\\0' '\\n' < /proc/$pid/environ 2>/dev/null | grep -E '^(TZ|PATH|HOME)=' "),
    ("进程 cwd", "pid=$(pgrep -f '[w]b2api' | head -1); ls -l /proc/$pid/cwd"),
    ("healthz", "wget -S -qO- http://127.0.0.1:7863/healthz 2>&1 | head -5; "
                "echo; curl -s -o /dev/null -w 'code=%{http_code}\\n' http://127.0.0.1:7863/healthz"),
    ("panel", "curl -s -o /dev/null -w 'code=%{http_code} size=%{size_download}\\n' http://127.0.0.1:7863/panel/"),
    ("files perm", "ls -l /etc/workbuddy2api/"),
    ("firewall", "uci show firewall | grep -iE 'wb2api|7863' ; echo '---'; "
                 "nft list ruleset 2>/dev/null | grep -i 7863 | head -5"),
    ("listen", "netstat -ltnp 2>/dev/null | grep 7863 || ss -ltnp 2>/dev/null | grep 7863"),
    ("opkg info", "opkg info workbuddy2api | head -12"),
    ("service state", "/etc/init.d/workbuddy2api running && echo RUNNING; "
                      "ubus call service list '{\"name\":\"workbuddy2api\"}' | head -30"),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, PASS, timeout=15, allow_agent=False, look_for_keys=False)
    for name, cmd in CMDS:
        _, out, err = c.exec_command(cmd, timeout=30)
        o = out.read().decode("utf-8", "replace").rstrip()
        e = err.read().decode("utf-8", "replace").rstrip()
        print("\n===== %s =====" % name)
        if o:
            print(o)
        if e:
            print("[stderr] " + e)
    c.close()


if __name__ == "__main__":
    sys.exit(main())
