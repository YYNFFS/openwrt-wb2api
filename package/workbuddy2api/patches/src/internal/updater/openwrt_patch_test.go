package updater

import "testing"

func TestReleaseNumbers(t *testing.T) {
	cases := []struct {
		in   string
		maj  int
		min  int
		note string
	}{
		{"24.10-SNAPSHOT", 24, 10, "ImmortalWrt 快照版"},
		{"24.10.0", 24, 10, "正式版"},
		{"23.05.5", 23, 5, "老版本"},
		{"22.03", 22, 3, "两段式"},
		{"SNAPSHOT", 0, 0, "没有数字"},
		{"", 0, 0, "空串"},
	}
	for _, c := range cases {
		maj, min := releaseNumbers(c.in)
		if maj != c.maj || min != c.min {
			t.Fatalf("releaseNumbers(%q) = %d,%d，期望 %d,%d（%s）", c.in, maj, min, c.maj, c.min, c.note)
		}
	}
}

func TestOpenWrtAssetNames(t *testing.T) {
	ver := "1.15.0+git20261122.24e59f8"
	old := openwrtEnv{Arch: "mipsel_24kc", Release: "23.05.5"}
	if got := old.mainAssetName(ver); got != "workbuddy2api_"+ver+"-1_mipsel_24kc-legacy.ipk" {
		t.Fatalf("23.05 主包名 = %q", got)
	}
	if got := old.luciAssetName(ver); got != "luci-app-workbuddy2api_"+ver+"-1_all-legacy.ipk" {
		t.Fatalf("23.05 LuCI 包名 = %q", got)
	}
	if !old.legacyContainer() {
		t.Fatal("23.05 应该用 -legacy 容器")
	}

	modern := openwrtEnv{Arch: "aarch64_cortex-a53", Release: "24.10-SNAPSHOT"}
	if got := modern.mainAssetName(ver); got != "workbuddy2api_"+ver+"-1_aarch64_cortex-a53.ipk" {
		t.Fatalf("24.10 主包名 = %q", got)
	}
	if modern.legacyContainer() {
		t.Fatal("24.10 不该用 -legacy 容器")
	}

	future := openwrtEnv{Arch: "x86_64", Release: "25.03.0"}
	if future.legacyContainer() {
		t.Fatal("25.03 不该用 -legacy 容器")
	}
	unknown := openwrtEnv{Arch: "x86_64", Release: "SNAPSHOT"}
	if unknown.legacyContainer() {
		t.Fatal("解析不出主版本时按新容器处理，不猜 -legacy")
	}
}

func TestShellQuote(t *testing.T) {
	if got := shellQuote("/tmp/wb2api-update/workbuddy2api_1.15.0+git20261122.24e59f8-1_x86_64.ipk"); got !=
		"'/tmp/wb2api-update/workbuddy2api_1.15.0+git20261122.24e59f8-1_x86_64.ipk'" {
		t.Fatalf("普通路径 = %q", got)
	}
	if got := shellQuote("/tmp/a b/c'd.ipk"); got != `'/tmp/a b/c'\''d.ipk'` {
		t.Fatalf("带空格与单引号 = %q", got)
	}
}

func TestParseVersionSemverTag(t *testing.T) {
	old, ok := parseVersion("v1.14.0+git20261120.be99749")
	if !ok {
		t.Fatal("v1.14.0+git20261120.be99749 应该能解析")
	}
	if old.text != "1.14.0+git20261120.be99749" {
		t.Fatalf("text = %q", old.text)
	}
	newer, ok := parseVersion("v1.15.0+git20261122.24e59f8")
	if !ok {
		t.Fatal("v1.15.0+git20261122.24e59f8 应该能解析")
	}
	if newer.ordinal <= old.ordinal {
		t.Fatalf("1.15.0 的序号 %d 应该大于 1.14.0 的 %d", newer.ordinal, old.ordinal)
	}
	sameBase, ok := parseVersion("1.15.0+git20261123.24e59f8")
	if !ok || sameBase.ordinal <= newer.ordinal {
		t.Fatal("同一基础版本按提交日期递增")
	}
	if _, ok := parseVersion("v1.2.3"); ok {
		t.Fatal("裸 semver 不算版本号（与上游约定一致）")
	}
	if _, ok := parseVersion("v1.15.0+git20261332.24e59f8"); ok {
		t.Fatal("非法日期要被拒")
	}
}
