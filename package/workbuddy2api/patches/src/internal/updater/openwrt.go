package updater

import (
	"context"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// openwrtEnv OpenWrt / ImmortalWrt 设备信息，来自 /etc/openwrt_release。
type openwrtEnv struct {
	Arch    string // DISTRIB_ARCH，如 aarch64_cortex-a53
	Release string // DISTRIB_RELEASE，如 24.10-SNAPSHOT
}

// updateDir 更新包落地目录。make_absolute 不依赖 /tmp 是 tmpfs：opkg 需要
// 完整读完包才动系统，放 /tmp 在内存小的机器上也够（单包 ~5 MB）。
const (
	updateDir        = "/tmp/wb2api-update"
	selfUpdateScript = "/tmp/wb2api-selfupdate.sh"
)

// openwrtInfo 识别 OpenWrt。判据是 /etc/openwrt_release 且能读到 DISTRIB_ARCH：
// 只有真正的 OpenWrt 系发行版才有这个文件，容器里也不会有。
func openwrtInfo() (openwrtEnv, bool) {
	if runtime.GOOS != "linux" {
		return openwrtEnv{}, false
	}
	raw, err := os.ReadFile("/etc/openwrt_release")
	if err != nil {
		return openwrtEnv{}, false
	}
	var env openwrtEnv
	for _, line := range strings.Split(string(raw), "\n") {
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		value = strings.Trim(strings.TrimSpace(value), "'\"")
		switch strings.TrimSpace(key) {
		case "DISTRIB_ARCH":
			env.Arch = value
		case "DISTRIB_RELEASE":
			env.Release = value
		}
	}
	if env.Arch == "" {
		return openwrtEnv{}, false
	}
	return env, true
}

// legacyContainer OpenWrt 24.10 起 ipk 容器从 ar 改成 tar.gz，本仓库两种都发，
// 老系统装 -legacy 那一份。
func (e openwrtEnv) legacyContainer() bool {
	major, minor := releaseNumbers(e.Release)
	if major == 0 {
		return false
	}
	return major < 24 || (major == 24 && minor < 10)
}

func (e openwrtEnv) suffix() string {
	if e.legacyContainer() {
		return "-legacy"
	}
	return ""
}

func (e openwrtEnv) mainAssetName(version string) string {
	return fmt.Sprintf("workbuddy2api_%s-1_%s%s.ipk", version, e.Arch, e.suffix())
}

func (e openwrtEnv) luciAssetName(version string) string {
	return fmt.Sprintf("luci-app-workbuddy2api_%s-1_all%s.ipk", version, e.suffix())
}

// releaseNumbers 从 "24.10-SNAPSHOT" / "23.05.3" 里取主次版本号；解析不出返回 0,0。
func releaseNumbers(release string) (int, int) {
	var parts []int
	cur := -1
	for _, r := range release {
		if r >= '0' && r <= '9' {
			if cur < 0 {
				cur = 0
			}
			cur = cur*10 + int(r-'0')
			continue
		}
		if cur >= 0 {
			parts = append(parts, cur)
			cur = -1
			if r == '.' {
				continue
			}
			break
		}
	}
	if cur >= 0 {
		parts = append(parts, cur)
	}
	if len(parts) == 0 {
		return 0, 0
	}
	minor := 0
	if len(parts) > 1 {
		minor = parts[1]
	}
	return parts[0], minor
}

// luciInstalled 判断本机是否装了 LuCI 界面包（决定要不要一起升级）。
func luciInstalled() bool {
	for _, p := range []string{
		"/usr/share/luci/menu.d/luci-app-workbuddy2api.json",
		"/etc/uci-defaults/90-workbuddy2api",
	} {
		if _, err := os.Stat(p); err == nil {
			return true
		}
	}
	return false
}

// installOpenWrt 在 OpenWrt 上安装新版本：下载 ipk → 校验 sha256 → 交给一个
// 脱离当前进程的 sh 脚本执行 `opkg install` + 重启服务。
//
// 为什么要绕一层脚本：opkg 会把 /usr/bin/wb2api 换掉，而本进程正在跑那个文件；
// 装完还要让 procd 重新拉起新二进制。让子进程 sleep 几秒后动手，父进程把 HTTP
// 响应先发出去，面板上看到的就是「安装中 → 服务重启 → 版本变了」。
func (m *Manager) installOpenWrt(ctx context.Context, r *release, version parsedVersion, env openwrtEnv) error {
	names := []string{env.mainAssetName(version.text)}
	if luciInstalled() {
		names = append(names, env.luciAssetName(version.text))
	}
	byName := make(map[string]*releaseAsset, len(r.Assets))
	for i := range r.Assets {
		byName[r.Assets[i].Name] = &r.Assets[i]
	}
	if err := os.MkdirAll(updateDir, 0o755); err != nil {
		return fmt.Errorf("创建更新目录: %w", err)
	}
	local := make([]string, 0, len(names))
	for _, name := range names {
		asset, ok := byName[name]
		if !ok {
			return fmt.Errorf("Release %s 里没有 %s（设备 %s，系统 %s）", version.text, name, env.Arch, env.Release)
		}
		dst := filepath.Join(updateDir, name)
		if err := m.downloadTo(ctx, asset, dst); err != nil {
			return err
		}
		log.Printf("[updater] 已下载 %s（%.1f MB，sha256 校验通过）", name, float64(asset.Size)/(1<<20))
		local = append(local, dst)
	}

	quoted := make([]string, len(local))
	for i, p := range local {
		quoted[i] = shellQuote(p)
	}
	script := strings.Join([]string{
		"#!/bin/sh",
		"# 由 wb2api 面板更新器生成：opkg 覆盖安装后重启服务",
		"sleep 3",
		"opkg install " + strings.Join(quoted, " "),
		"rc=$?",
		"if [ $rc -eq 0 ]; then /etc/init.d/workbuddy2api restart; fi",
		"rm -f " + strings.Join(quoted, " ") + " " + selfUpdateScript,
		"exit $rc",
	}, "\n") + "\n"
	if err := os.WriteFile(selfUpdateScript, []byte(script), 0o700); err != nil {
		return fmt.Errorf("写入更新脚本: %w", err)
	}
	if err := launchDetachedShell(selfUpdateScript); err != nil {
		os.Remove(selfUpdateScript)
		return fmt.Errorf("启动更新脚本: %w", err)
	}
	log.Printf("[updater] 已准备 %s，3 秒后 opkg 覆盖安装并重启服务", version.text)
	m.mu.Lock()
	m.status.LastError = ""
	m.mu.Unlock()
	m.armInstallWatchdog()
	return nil
}

// downloadTo 按 Release 资产把文件落到本地并核对 sha256（GitHub 上传时算的 digest）。
func (m *Manager) downloadTo(ctx context.Context, asset *releaseAsset, dst string) error {
	if asset.Size <= 0 || asset.Size > maxArchiveSize {
		return fmt.Errorf("Release 文件大小异常: %d", asset.Size)
	}
	if !hasSHA256Digest(asset.Digest) {
		return errors.New("Release 未提供有效 SHA-256 摘要，已取消安装")
	}
	f, err := os.Create(dst)
	if err != nil {
		return fmt.Errorf("创建下载文件: %w", err)
	}
	ok := false
	defer func() {
		if !ok {
			f.Close()
			os.Remove(dst)
		}
	}()
	if err := m.downloadAsset(ctx, asset, f); err != nil {
		return err
	}
	if err := f.Sync(); err != nil {
		return fmt.Errorf("同步下载文件: %w", err)
	}
	if err := f.Close(); err != nil {
		return fmt.Errorf("关闭下载文件: %w", err)
	}
	if err := verifySHA256(dst, strings.TrimPrefix(asset.Digest, "sha256:")); err != nil {
		m.mu.Lock()
		m.status.LastErrorKind = kindChecksum
		m.mu.Unlock()
		return fmt.Errorf("%w（[%s] %s）", err, kindChecksum, adviceFor(kindChecksum))
	}
	ok = true
	return nil
}

// shellQuote 单引号包裹并把内部单引号转义，路径里带 + 号（版本号）也不再出问题。
func shellQuote(s string) string {
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}
