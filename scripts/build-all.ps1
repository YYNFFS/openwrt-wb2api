<#
  交叉编译全部架构的 wb2api 二进制，然后打成 ipk（Windows 版）。

  用法：
    powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1
    powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1 -Version 1.14.0 -GoRoot D:\go
    powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1 -SkipPack   # 只编二进制
#>
param(
	[string]$GoRoot = $env:GOROOT,
	[string]$Python = "python",
	[string]$Version = "1.14.0",
	[switch]$SkipPack
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Src  = Join-Path $Root 'package\workbuddy2api\src'
$Out  = Join-Path $Root 'prebuilt'
$Dist = Join-Path $Root 'dist'

if (-not $GoRoot -or -not (Test-Path (Join-Path $GoRoot 'bin\go.exe'))) {
	$cmd = Get-Command go -ErrorAction SilentlyContinue
	if ($cmd) { $GoRoot = Split-Path -Parent (Split-Path -Parent $cmd.Source) }
	else { throw "找不到 go，请用 -GoRoot 指定 Go 安装目录" }
}

$env:GOROOT = $GoRoot
$env:PATH = "$GoRoot\bin;$env:PATH"
$env:GOTOOLCHAIN = 'auto'     # go.mod 要求 1.26.10，本地 1.23 会自动拉工具链
$env:CGO_ENABLED = '0'        # 静态链接，不依赖路由器 libc 版本
$env:GOOS = 'linux'
$env:GOFLAGS = '-mod=vendor'  # 离线编译

New-Item -ItemType Directory -Force -Path $Out, $Dist | Out-Null

$LdFlags = "-s -w -X main.appVersion=$Version"

$targets = @(
	@{ n = 'mipsle'; a = 'mipsle'; e = @{ GOMIPS = 'softfloat' } },
	@{ n = 'mips';   a = 'mips';   e = @{ GOMIPS = 'softfloat' } },
	@{ n = 'armv7';  a = 'arm';    e = @{ GOARM = '7' } },
	@{ n = 'armv6';  a = 'arm';    e = @{ GOARM = '6' } },
	@{ n = 'arm64';  a = 'arm64';  e = @{} },
	@{ n = 'amd64';  a = 'amd64';  e = @{} },
	@{ n = '386';    a = '386';    e = @{} }
)

Push-Location $Src
try {
	foreach ($t in $targets) {
		$env:GOARCH = $t.a
		foreach ($k in @('GOMIPS', 'GOARM')) { Remove-Item "env:$k" -ErrorAction SilentlyContinue }
		foreach ($k in $t.e.Keys) { Set-Item "env:$k" $t.e[$k] }

		Write-Host ">> linux/$($t.a) -> wb2api-linux-$($t.n)"
		$dst = Join-Path $Out "wb2api-linux-$($t.n)"
		& go build -trimpath -buildvcs=false -ldflags $LdFlags -o $dst ./cmd/server
		if ($LASTEXITCODE -ne 0) { throw "build $($t.n) failed" }
	}
}
finally {
	Pop-Location
	Remove-Item env:GOMIPS, env:GOARM, env:GOFLAGS -ErrorAction SilentlyContinue
}

if ($SkipPack) {
	Write-Host "`n== prebuilt =="
	Get-ChildItem $Out | Select-Object Name, Length
	return
}

# 两种容器格式都出：tgz = OpenWrt 24.10+，ar = 22.03/23.05 的 legacy
& $Python (Join-Path $Root 'scripts\build-ipk.py') --all --format both --out $Dist
if ($LASTEXITCODE -ne 0) { throw "build-ipk.py failed" }

Write-Host "`n== dist =="
Get-ChildItem $Dist | Select-Object Name, Length
