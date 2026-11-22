package updater

import (
	"regexp"
	"strconv"
	"strings"
)

// parseVersion 解析 Release tag 为可比较的序号。
//
// 两条来源都要认：
//  1. 本仓库打包标签 1.14.0+git20261122.24e59f8（见 parseSemverVersion）——
//     OpenWrt 打包仓每次跟随上游都会造这种 tag，面板要能认出它；
//  2. 上游时间标签 2026.9.26.711 —— 保留 parseStampVersion 原实现，
//     万一切回上游发版方式也不需要再动代码。
//
// 注意：裸的 1.2.3 不算版本号（上游既有约定，别让随手写的 semver 冒充 Release）。
func parseVersion(tag string) (parsedVersion, bool) {
	text := strings.TrimPrefix(tag, "v")
	if v, ok := parseSemverVersion(text); ok {
		return v, true
	}
	return parseStampVersion(text)
}

// semverPattern 本仓库的打包标签：<上游版本>+git<YYYYMMDD>.<短sha>。
var semverPattern = regexp.MustCompile(`^([0-9]{1,4})\.([0-9]{1,4})\.([0-9]{1,4})\+git([0-9]{8})\.([0-9a-fA-F]{7,40})$`)

// parseSemverVersion 本仓库方案。序号布局：主*1e17 + 次*1e14 + 修订*1e11 +
// 提交日期*1e3 + sha 首字节，保证「基础版本优先、同版本按提交日期、同日按 sha」
// 三层比较都单调；日期项 1e3 倍后仍小于 1e11，不会串到修订号上。
func parseSemverVersion(text string) (parsedVersion, bool) {
	m := semverPattern.FindStringSubmatch(text)
	if m == nil {
		return parsedVersion{}, false
	}
	major, err := strconv.Atoi(m[1])
	if err != nil {
		return parsedVersion{}, false
	}
	minor, err := strconv.Atoi(m[2])
	if err != nil {
		return parsedVersion{}, false
	}
	revision, err := strconv.Atoi(m[3])
	if err != nil {
		return parsedVersion{}, false
	}
	date, err := strconv.ParseInt(m[4], 10, 64)
	if err != nil {
		return parsedVersion{}, false
	}
	// 日期必须是真的日期，20261332 这种要当非法。
	if len(m[4]) != 8 {
		return parsedVersion{}, false
	}
	year, month, day := date/10000, (date/100)%100, date%100
	if year < 2000 || year > 9999 || month < 1 || month > 12 || day < 1 || day > 31 {
		return parsedVersion{}, false
	}
	shaByte, err := strconv.ParseUint(m[5][:2], 16, 8)
	if err != nil {
		return parsedVersion{}, false
	}
	ordinal := int64(major)*1e17 + int64(minor)*1e14 + int64(revision)*1e11 + date*1e3 + int64(shaByte)
	return parsedVersion{text: text, ordinal: ordinal}, true
}
