#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从上游 config.example.json 生成 OpenWrt 出厂配置 config.default.json。

差异只保留「路由器场景必须改」的项：
  - listen 改成 0.0.0.0:7863（例子默认只监听回环，局域网上打不开面板）
  - auth_dir / state_file / audit_file 改成 /etc/workbuddy2api 下的绝对路径
  - 请求归档默认关闭、条数与容量压到最小（闪存写放大）
  - 面板日志同样压到 3 天 / 8 MiB
  - 自更新默认关闭（固件里的二进制由 opkg 管，不走进程内自替换）

上游新增的任何字段都会被原样带过来，不会因为本脚本漏项而丢配置项。
去掉以 "_" 开头的注释键（Go 侧会忽略，但出厂文件保持干净）。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "package" / "workbuddy2api" / "src" / "config.example.json"
OUT = ROOT / "package" / "workbuddy2api" / "files" / "config.default.json"

OVERRIDES = {
    "listen": "0.0.0.0:7863",
    "auth_dir": "/etc/workbuddy2api/auths",
    "state_file": "/etc/workbuddy2api/data/state.json",
}

NESTED = {
    ("logging", "request_archive_enabled"): False,
    ("logging", "request_retention_days"): 3,
    ("logging", "request_archive_max_mb"): 16,
    ("logging", "panel_log_enabled"): True,
    ("logging", "panel_log_retention_days"): 3,
    ("logging", "panel_log_max_mb"): 8,
    ("admin", "audit_file"): "/etc/workbuddy2api/data/admin_audit.log",
    ("update", "auto_enabled"): False,
}


def strip_comments(obj):
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_comments(v) for v in obj]
    return obj


def main() -> int:
    raw = json.loads(EX.read_text(encoding="utf-8"))
    cfg = strip_comments(raw)

    for k, v in OVERRIDES.items():
        cfg[k] = v

    for (sec, key), val in NESTED.items():
        node = cfg.setdefault(sec, {})
        if not isinstance(node, dict):
            print("警告: 配置段 %s 不是对象，跳过 %s" % (sec, key), file=sys.stderr)
            continue
        node[key] = val

    OUT.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("已生成 %s" % OUT)
    print("  段: %s" % ", ".join(sorted(cfg.keys())))
    print("  listen=%s auth_dir=%s" % (cfg["listen"], cfg["auth_dir"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
