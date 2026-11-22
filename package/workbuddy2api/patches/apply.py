#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本仓库对上游源码的改动重新打到 package/workbuddy2api/src 上。

为什么需要它：scripts/sync-upstream.sh 用 rsync --delete 把上游 src 整体覆盖，
本地对 src 的任何改动都会在下次跟随上游时消失。所有 src 改动因此都收敛到这里，
同步脚本与构建脚本都会调用本脚本，保证「同步 → 打补丁 → 编译」这条链可重放。

改动清单（每一项都幂等，重复执行不会叠加）：
  1. 覆盖写入 internal/updater/openwrt.go   —— OpenWrt 上的 opkg 更新路径
  2. 覆盖写入 internal/updater/version.go   —— 认本仓库 1.14.0+git… 形式的 tag
  3. updater.go: 上游 parseVersion 改名 parseStampVersion，交给我们的 parseVersion 调度
  4. updater.go: New() 的空仓库兜底指向本仓库
  5. updater.go: canInstallLocked() 放开 OpenWrt（ipk 走 opkg，不需要 amd64/arm64 的 zip）
  6. updater.go: Install() 在 OpenWrt 上分支到 installOpenWrt()
  7. process_unix.go / process_windows.go: 追加 launchDetachedShell()
  8. cmd/server/main.go: appRepository 指向本仓库（面板「打开 Release」跟随）
  9. internal/panel/index.html: 更新区文案改成 opkg 口径

用法：
    python3 package/workbuddy2api/patches/apply.py            # 打补丁
    python3 package/workbuddy2api/patches/apply.py --check    # 只检查是否已打全

退出码：0 = 全部落地；1 = 有锚点没找到（上游改结构了，需要人工看）
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)                      # package/workbuddy2api
SRC = os.path.join(PKG, "src")

REPO = "YYNFFS/openwrt-wb2api"

# 覆盖式写入的新文件（相对 src）
NEW_FILES = [
    "internal/updater/openwrt.go",
    "internal/updater/version.go",
    "internal/updater/openwrt_patch_test.go",
]

UNIX_SHELL_HELPER = '''
// launchDetachedShell 用 /bin/sh 跑一个脚本并脱离当前会话（setsid）：
// 父进程重启 / 被 procd 杀掉都不会把安装过程带走。
func launchDetachedShell(script string) error {
	cmd := exec.Command("/bin/sh", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	devnull, err := os.OpenFile(os.DevNull, os.O_RDWR, 0)
	if err != nil {
		return err
	}
	cmd.Stdin, cmd.Stdout, cmd.Stderr = devnull, devnull, devnull
	setHiddenWindow(cmd)
	if err := cmd.Start(); err != nil {
		devnull.Close()
		return err
	}
	go func() {
		_ = cmd.Wait()
		devnull.Close()
	}()
	return nil
}
'''

WINDOWS_SHELL_HELPER = '''
// launchDetachedShell Windows 上没有 opkg 更新路径，保留签名以便跨平台编译。
func launchDetachedShell(string) error {
	return errors.New("Windows 上不支持 shell 安装脚本")
}
'''

CAN_INSTALL_LOCKED = '''func (m *Manager) canInstallLocked() bool {
	if _, versioned := parseVersion(m.version); !versioned || m.executable == "" {
		return false
	}
	if isContainer() || processSupervised() {
		return false
	}
	// OpenWrt：本仓库 Release 发的是 ipk，安装由 opkg 完成，不受
	// 「只有 linux/windows 的 amd64/arm64 能原地替换 zip」这条限制约束。
	if _, ok := openwrtInfo(); ok {
		return runtime.GOOS == "linux"
	}
	return (runtime.GOOS == "linux" || runtime.GOOS == "windows") &&
		(runtime.GOARCH == "amd64" || runtime.GOARCH == "arm64")
}'''

INSTALL_BRANCH = '''	// OpenWrt：Release 里是 ipk，交给 opkg 安装（见 openwrt.go）。
	if env, isOpenWrt := openwrtInfo(); isOpenWrt {
		return m.installOpenWrt(ctx, r, version, env)
	}
'''

PANEL_HINT_OLD = "每天按上海时间检查并安装新的时间标签版 Release；容器部署请更新镜像。"
PANEL_HINT_NEW = (
    "每天按上海时间检查并安装新的 Release；OpenWrt 上一键更新走 opkg"
    "（下载 ipk 后覆盖安装并重启服务），容器部署请更新镜像。"
)


def read(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def drop_gitignore_dirs(root):
    """上游 .gitignore 里有 `*.md`，同步脚本删的是文件，这里兜住残留目录规则。"""
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name == ".gitignore":
                os.remove(os.path.join(dirpath, name))


def find_brace_end(text, start):
    """从 `{` 位置起找到配对的 `}`，跳过字符串、字符、行注释与块注释。"""
    assert text[start] == "{", "find_brace_end 需要从 { 开始"
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "`":
            quote = c
            i += 1
            while i < n:
                if quote == '"' and text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    break
                i += 1
            i += 1
            continue
        if c == "'":
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == "'":
                    break
                i += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("大括号没有配对")


def replace_func(text, signature, new_body):
    """把以 signature 开头的整个函数替换成 new_body；找不到返回 None。"""
    idx = text.find(signature)
    if idx < 0:
        return None
    brace = text.find("{", idx)
    if brace < 0:
        return None
    end = find_brace_end(text, brace)
    return text[:idx] + new_body + text[end + 1:]


def apply(check_only=False):
    results = []
    failed = []

    def ok(name, applied):
        results.append((name, "applied" if applied else "skipped(already)"))

    def bad(name, why):
        failed.append("%s: %s" % (name, why))

    # --- 1/2. 覆盖式新文件 -------------------------------------------------
    for rel in NEW_FILES:
        src_file = os.path.join(HERE, "src", rel)
        dst_file = os.path.join(SRC, rel)
        if not os.path.exists(src_file):
            bad(rel, "patches/src 里缺这份文件")
            continue
        want = read(src_file)
        have = read(dst_file) if os.path.exists(dst_file) else None
        if have == want:
            ok(rel, False)
            continue
        if not check_only:
            write(dst_file, want)
        ok(rel, True)

    # --- 3/4/5/6. internal/updater/updater.go ------------------------------
    upd = os.path.join(SRC, "internal/updater/updater.go")
    if not os.path.exists(upd):
        bad("internal/updater/updater.go", "文件不存在")
    else:
        text = read(upd)
        changed = False

        # 3. 上游 parseVersion 改名，避免和 version.go 里的同名函数冲突。
        old_sig = "func parseVersion(tag string) (parsedVersion, bool) {"
        new_sig = "func parseStampVersion(tag string) (parsedVersion, bool) {"
        if new_sig in text:
            ok("updater.go::parseVersion 改名", False)
        elif old_sig in text:
            text = text.replace(old_sig, new_sig, 1)
            changed = True
            ok("updater.go::parseVersion 改名", True)
        else:
            bad("updater.go::parseVersion 改名", "找不到上游 parseVersion 签名")

        # 4. New() 兜底仓库
        if 'repository = "%s"' % REPO in text:
            ok("updater.go::兜底仓库", False)
        elif 'repository = "misakano7545/workbuddy2api-panel"' in text:
            text = text.replace(
                'repository = "misakano7545/workbuddy2api-panel"',
                'repository = "%s"' % REPO,
                1,
            )
            changed = True
            ok("updater.go::兜底仓库", True)
        else:
            bad("updater.go::兜底仓库", "找不到空仓库兜底那一行")

        # 5. canInstallLocked：只看函数体里有没有我们的 OpenWrt 判断，
        #    不要看整个文件（别的地方也可能提到 openwrtInfo）。
        if "func (m *Manager) canInstallLocked()" in text:
            idx = text.find("func (m *Manager) canInstallLocked()")
            end = find_brace_end(text, text.find("{", idx))
            body = text[idx:end + 1]
            if "openwrtInfo()" in body:
                ok("updater.go::canInstallLocked", False)
            else:
                new_text = replace_func(text, "func (m *Manager) canInstallLocked()", CAN_INSTALL_LOCKED)
                if new_text is None:
                    bad("updater.go::canInstallLocked", "函数体替换失败")
                else:
                    text = new_text
                    changed = True
                    ok("updater.go::canInstallLocked", True)
        else:
            bad("updater.go::canInstallLocked", "找不到该函数")

        # 6. Install() 里的 OpenWrt 分支：插在拼 zip 资产名之前
        if "m.installOpenWrt(ctx, r, version, env)" in text:
            ok("updater.go::OpenWrt 安装分支", False)
        elif 'assetName := fmt.Sprintf("wb2api-panel-' in text:
            def _insert(match):
                indent = match.group(1)
                lines = [indent + line.lstrip("\t") if line.strip() else line
                         for line in INSTALL_BRANCH.rstrip("\n").split("\n")]
                return "\n".join(lines) + "\n" + match.group(0)

            text = re.sub(
                r'(?m)^([ \t]*)assetName := fmt\.Sprintf\("wb2api-panel-',
                _insert,
                text,
                count=1,
            )
            changed = True
            ok("updater.go::OpenWrt 安装分支", True)
        else:
            bad("updater.go::OpenWrt 安装分支", "找不到拼 zip 资产名的位置")

        if changed and not check_only:
            write(upd, text)

    # --- 7. process_unix.go / process_windows.go ---------------------------
    for rel, helper, marker in (
        ("internal/updater/process_unix.go", UNIX_SHELL_HELPER, "func launchDetachedShell(script string) error {"),
        ("internal/updater/process_windows.go", WINDOWS_SHELL_HELPER, "func launchDetachedShell(string) error {"),
    ):
        path = os.path.join(SRC, rel)
        if not os.path.exists(path):
            bad(rel, "文件不存在")
            continue
        text = read(path)
        if marker in text:
            ok(rel + "::launchDetachedShell", False)
            continue
        if not check_only:
            if not text.endswith("\n"):
                text += "\n"
            write(path, text + helper)
        ok(rel + "::launchDetachedShell", True)

    # --- 8. cmd/server/main.go --------------------------------------------
    main_go = os.path.join(SRC, "cmd/server/main.go")
    if not os.path.exists(main_go):
        bad("cmd/server/main.go", "文件不存在")
    else:
        text = read(main_go)
        if 'var appRepository = "%s"' % REPO in text:
            ok("main.go::appRepository", False)
        elif "var appRepository" in text:
            lines = text.split("\n")
            done = False
            for i, line in enumerate(lines):
                if line.startswith("var appRepository"):
                    lines[i] = 'var appRepository = "%s"' % REPO
                    done = True
                    break
            if done:
                if not check_only:
                    write(main_go, "\n".join(lines))
                ok("main.go::appRepository", True)
            else:
                bad("main.go::appRepository", "行首没找到 var appRepository")
        else:
            bad("main.go::appRepository", "找不到变量声明")

    # --- 9. internal/panel/index.html -------------------------------------
    panel = os.path.join(SRC, "internal/panel/index.html")
    if not os.path.exists(panel):
        bad("internal/panel/index.html", "文件不存在")
    else:
        text = read(panel)
        if PANEL_HINT_NEW in text:
            ok("index.html::更新文案", False)
        elif PANEL_HINT_OLD in text:
            if not check_only:
                write(panel, text.replace(PANEL_HINT_OLD, PANEL_HINT_NEW, 1))
            ok("index.html::更新文案", True)
        else:
            bad("index.html::更新文案", "找不到原文案（上游改过这句？）")

    print("== 补丁结果（%s）" % ("仅检查" if check_only else "已应用"))
    for name, state in results:
        print("   %-40s %s" % (name, state))
    if failed:
        print("\n!! 有锚点没找到，上游结构可能变了：")
        for item in failed:
            print("   " + item)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="给 package/workbuddy2api/src 打本仓库的改动补丁")
    ap.add_argument("--check", action="store_true", help="只检查，不写文件")
    args = ap.parse_args()
    if not os.path.isdir(SRC):
        print("找不到源码目录: %s" % SRC, file=sys.stderr)
        return 2
    return apply(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
