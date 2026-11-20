# WorkBuddy2API · OpenWrt 插件

把 [workbuddy2api-panel](https://github.com/misakano7545/workbuddy2api-panel)（CodeBuddy / WorkBuddy
账号池 → OpenAI 兼容网关，自带 Web 管理面板）封装成标准 OpenWrt 软件包：

- **主程序包 `workbuddy2api`**：Go 静态二进制 + procd 服务脚本 + UCI 配置，装完即用。
- **界面包 `luci-app-workbuddy2api`**：LuCI 菜单「服务 → WorkBuddy2API」，含概览 / 设置 / 账号 / 日志。

二进制 `CGO_ENABLED=0` 静态编译，不依赖 libc 版本，也不需要 python / bash / redis。

> 本版对应上游 **1.14.0**（commit `be99749`，2026-11-20）。
> 打包层曾在 **Cudy TR3000 v1（MT7981）+ ImmortalWrt 24.10-SNAPSHOT** 实机安装验证；
> 1.14.0-1 全部 32 个包已通过 `scripts/verify-ipk.py` 结构校验，二进制在 Windows 上做过同源冒烟
> （`/panel/`、`/v1/models`、`/panel/api/overview` 均正常返回）。

## 0. 仓库、下载与自动跟随上游

| 项 | 地址 |
| --- | --- |
| 本仓库（打包层 + CI） | <https://github.com/YYNFFS/openwrt-wb2api> |
| 成品 ipk 下载 | <https://github.com/YYNFFS/openwrt-wb2api/releases/latest> |
| 上游网关项目 | <https://github.com/misakano7545/workbuddy2api-panel> |

Releases 里的资产就是 `dist/` 下那 32 个包 + `SHA256SUMS.txt`，直接下载对应架构装即可，
不需要自己编。文件名规则：`workbuddy2api_<版本>_<架构>.ipk`（24.10+，tar.gz 容器）与
`workbuddy2api_<版本>_<架构>-legacy.ipk`（22.03/23.05，ar 容器）。

### 自动跟随上游

仓库带两个 GitHub Actions 工作流，上游一有提交就自动出新包：

| 工作流 | 触发 | 干什么 |
| --- | --- | --- |
| `.github/workflows/sync-upstream.yml` | 每 6 小时 cron、手动 | 比对上游 HEAD 与 `.upstream-commit`；有变化就 rsync 源码 → `go mod vendor` → 重生成 `config.default.json` → 重算版本号 → 提交并 push |
| `.github/workflows/build.yml` | push 到 main（改 `package/`、`scripts/`）、手动、每周一 | 交叉编译 7 个架构二进制 → 打 15 架构 × 2 容器的 ipk → `verify-ipk.py` 校验 → 发布 Release |

同步工作流用内置 `GITHUB_TOKEN` 提交，而 GitHub 规定这类提交产生的 push 事件不会启动其它工作流，
所以工作流在推送成功后显式 `gh workflow run build.yml` 派发一次构建（需要 `actions: write` 权限，已写在 yml 里）。
整条链路是：**上游提交 → 自动同步 → 自动编译 → 自动发布**。

只想重建一次包（比如 Release 资产被删了）：Actions → `sync-upstream` → Run workflow → 勾 `rebuild`，
它会跳过同步直接派发 `build.yml`；或直接跑 `build-ipk` 工作流。

### 版本号规则

上游没有 tag，也没有版本常量（`main.go` 里是 `var appVersion = "dev"`，由 `-ldflags -X` 注入），
所以包版本由本仓库生成：

```
<基础版本>+git<上游提交日期 YYYYMMDD>.<上游 commit 前 7 位>
例：1.14.0+git20261120.be99749
```

`+` 之后的部分让 opkg 认得出「这是同一基础的更新版本」，升级时能正常覆盖。
基础版本存在 `package/workbuddy2api/Makefile` 的 `PKG_VERSION`，想手动切到别的系列改这里即可。

记录文件（同步工作流与构建工作流共用）：

| 文件 | 含义 |
| --- | --- |
| `.upstream-commit` | 已同步的上游完整 commit |
| `.upstream-date` | 该 commit 的提交日期（`%cs`） |
| `.upstream-subject` | 该 commit 的标题，写进 Release 说明 |
| `.upstream-version` | 本次包版本，`build-ipk.py` 与 `build-all.sh` 都读它 |

### 本地手动同步

```sh
bash scripts/sync-upstream.sh          # 拉上游最新 → 同步源码 → vendor → 重算版本
bash scripts/build-all.sh              # 本地交叉编译 + 打包（需要 go / python3 / rsync）
```

想跟别的 fork：`UPSTREAM_URL=https://github.com/<你>/<fork>.git bash scripts/sync-upstream.sh`，
或用工作流的环境变量 `UPSTREAM_URL`。

### Fork 后自己跑

1. fork 本仓库；
2. 把 `.github/workflows/sync-upstream.yml` 里的 `UPSTREAM_URL` 换成你要跟的上游；
3. Settings → Actions → General → Workflow permissions 选 **Read and write permissions**（同步工作流要 push 回仓库）；
4. 想立刻出一次包：Actions → `sync-upstream` → Run workflow（勾 `force` 可强制重建同版本）。

---

---

## 1. 兼容性

| 项目 | 要求 |
|---|---|
| 主程序包 | OpenWrt 22.03 及以上 |
| LuCI 界面包 | **OpenWrt 23.05 / 24.10**（JS 版 LuCI）；21.02、22.03 是 Lua 版，装主包后直接用网关自带面板 |
| 内存 | 建议 ≥ 128 MB 可用 |
| 存储 | 程序 + 数据约 20 MB（单包解包 13.4–15.7 MiB） |

### ⚠️ ipk 容器格式（很重要）

OpenWrt **24.10 起把 ipk 容器从 `ar` 改成了 `tar.gz`**，两种格式互不通用：

| 系统版本 | 该用哪个文件 |
|---|---|
| OpenWrt / ImmortalWrt **24.10 及以上** | `workbuddy2api_1.14.0-1_<arch>.ipk` |
| OpenWrt **22.03 / 23.05** | `workbuddy2api_1.14.0-1_<arch>-legacy.ipk` |

装错会报 `Malformed package file` 或 `pkg_init_from_file` 错误，换另一个即可。
LuCI 包同理（`luci-app-workbuddy2api_1.14.0-1_all.ipk` / `..._all-legacy.ipk`）。

### 架构对照

在路由器上执行 `opkg print-architecture | tail -1` 得到设备架构，再选对应 ipk：

| 设备架构 | 典型设备 |
|---|---|
| `mipsel_24kc` | MT7620 / MT7621 / MT7628（小米、Newifi、K2P、极路由，**最常见**） |
| `mipsel_74kc` / `mipsel_1004kc` | 部分博通、高通老平台 |
| `mips_24kc` / `mips_74kc` | 大端 MIPS（少见） |
| `arm_cortex-a7` / `arm_cortex-a7_neon-vfpv4` | IPQ40xx、MT7622 |
| `arm_cortex-a9` / `arm_cortex-a9_vfpv3-d16` | 博通 BCM53xx 等 |
| `arm_cortex-a5_vfpv4` / `arm_arm1176jzf-s_vfp` | 老 ARMv6/v7 设备 |
| `aarch64_cortex-a53` / `aarch64_generic` | MT7981 / MT7986（AX3000T、Cudy TR3000）、R2S/R4S、IPQ60xx |
| `x86_64` / `i386_pentium4` | 软路由 |

15 个架构 × 2 种容器 + 2 个 LuCI 包 = `dist/` 下 32 个 ipk。
包体积：主程序 **5.1–5.8 MB**，LuCI 包 **7.2 KB**；`SHA256SUMS.txt` 里是全部 32 个包的校验值。

---

## 2. 安装

```sh
# 1) 上传到 /tmp（scp / WinSCP / LuCI 上传均可）
# 2) 主程序（换成你设备的架构与格式）
opkg install /tmp/workbuddy2api_1.14.0-1_aarch64_cortex-a53.ipk

# 3) LuCI 界面（23.05+ 才需要）
opkg install /tmp/luci-app-workbuddy2api_1.14.0-1_all.ipk
```

安装脚本会自动：创建 `/etc/workbuddy2api/`、从出厂模板生成带随机 `api_key` 的 `config.json`、
设置开机自启、启动服务、在防火墙放行 LAN 侧 TCP 7863。

```sh
grep '"api_key"' /etc/workbuddy2api/config.json
```

浏览器打开 `http://<路由器IP>:7863/panel/` 即为网关自带管理面板。

### 一键部署（局域网内，SSH 已开启）

```sh
pip install paramiko
python3 scripts/deploy.py --host 192.168.6.1 --password <root密码>
python3 scripts/deploy.py --password <root密码> --reinstall   # 先卸载再装，清掉旧 conffiles
python3 scripts/deploy.py --password <root密码> --skip-luci   # 只更新主程序
```

脚本会读设备 `/etc/openwrt_release` 的 `DISTRIB_ARCH`、自动挑对应 ipk、SFTP 上传、
opkg 安装并打印验证结果；`--arch x86_64` 可强指定。

### 升级 / 回滚

```sh
# 升级：直接把新 ipk 丢上去覆盖（conffiles 里的 UCI 与出厂模板会保留）
opkg install /tmp/workbuddy2api_1.14.0-1_aarch64_cortex-a53.ipk
# 配置文件不会被覆盖；旧 config.json 缺的新字段由程序按其默认值补齐
```

旧版（1.13.0）的 `config.json` 与新 schema 有差异（见第 6 节），升级后建议在面板里逐项确认
`pool.selection_strategy`、`update.auto_enabled`、`logging.panel_log_*`。

---

## 3. 首次使用

1. 打开 `http://<路由器IP>:7863/panel/`。
2. 「账号」→「添加账号」，按提示在浏览器完成 CodeBuddy / WorkBuddy 设备授权，
   凭证写入 `/etc/workbuddy2api/auths/`。
3. 调用 OpenAI 兼容接口：

```bash
curl http://192.168.6.1:7863/v1/chat/completions \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-5.2","messages":[{"role":"user","content":"hi"}]}'
```

```
base_url = http://192.168.6.1:7863/v1
api_key  = <api_key>
```

签到、保活、猫猫旅行、成长任务等定时任务在面板里开关。**注意**：这些任务按进程时区
计算整点，时区配置见第 6 节（Go 不认 POSIX 的 `CST-8`）。

---

## 4. LuCI 界面

菜单：**服务 → WorkBuddy2API**

| 页面 | 功能 |
|---|---|
| 概览 | 运行状态、监听地址、账号数量、面板入口，启停 / 重启 / 开机自启 |
| 设置 | 监听地址、API Key（可一键重新生成）、账号目录、状态文件、日志归档；高级区可直接编辑完整 `config.json`；可恢复出厂配置 |
| 账号 | 列出 `auths/` 下的凭证文件（大小 / 修改时间），可删除并重启服务 |
| 日志 | `logread` 实时输出，可开关自动刷新 |

时区项写的是 UCI 的 `zonename`（IANA 名，默认 `Asia/Shanghai`）。
1.14.0-1 修掉了旧版一处失效实现：页面原来写 `timezone`、init 脚本读 `zonename`，改完不生效。

改动保存后立即重启服务生效。

---

## 5. 文件布局

| 路径 | 说明 |
|---|---|
| `/usr/bin/wb2api` | 主程序（静态二进制，14–16 MB） |
| `/etc/init.d/workbuddy2api` | procd 服务脚本 |
| `/etc/config/workbuddy2api` | UCI 配置（自启 / 时区 / 额外参数） |
| `/etc/workbuddy2api/config.json` | 主配置（首次启动生成，含随机 api_key） |
| `/etc/workbuddy2api/config.default.json` | 出厂模板（`conffiles` 保护） |
| `/etc/workbuddy2api/zoneinfo/Asia/Shanghai` | 包内自带 TZif，给 Go 用的时区文件（393 B） |
| `/etc/workbuddy2api/auths/` | 账号凭证 `workbuddy-<uid>.json` |
| `/etc/workbuddy2api/data/` | `state.json` 池状态、`usage.json` 用量、`credit-history.json` 积分历史、`admin_audit.log` 后台审计 |
| `/etc/workbuddy2api/data/request-logs/` | 请求归档（默认关闭） |

配置里的 `auth_dir` / `state_file` / `admin.audit_file` 都是**绝对路径**（不依赖进程 cwd ——
部分 procd 版本会忽略 `cwd` 参数，早期版本因此把数据写到了 `/` 下，升级后会自动迁移）。

### 闪存磨损提示

- `state.json` 只在状态变化时落盘（内部 5 秒节流），空闲不写。
- **请求归档默认关闭**（`logging.request_archive_enabled=false`）。要用面板的历史日志查询可在
  设置页开启，并配合 `request_retention_days=3`、`request_archive_max_mb=16`；
  长期高频调用建议保持关闭，或把「状态文件」改到 `/tmp` / U 盘（父目录会自动创建）。
- 面板自带日志同样限流：`panel_log_enabled=true`、`panel_log_retention_days=3`、
  `panel_log_max_mb=8`。
- 自动更新默认关闭：`update.auto_enabled=false`（路由器上不需要它自己下 GitHub Release）。

---

## 6. 配置说明

### UCI（`/etc/config/workbuddy2api`）

```uci
config workbuddy2api 'main'
	option enabled '1'              # 开机自启
	option respawn '1'              # 异常退出由 procd 拉起
	option zonename 'Asia/Shanghai' # IANA 时区名，见下
	option extra_args ''            # 追加到命令行的参数
```

改完 `uci commit workbuddy2api && /etc/init.d/workbuddy2api restart`。

### 为什么不是 `timezone 'CST-8'`

busybox 认 POSIX 的 `CST-8`，但 **Go 只认 tzdata 文件**（`TZ` 为 IANA 名或绝对路径）。
路由器默认不装 `zoneinfo` 包，所以本插件自带一份 `Asia/Shanghai` 的 TZif，
启动时设 `TZ=/etc/workbuddy2api/zoneinfo/Asia/Shanghai`。

换其它时区：装 `zoneinfo-<region>` 包后把 `zonename` 改成对应 IANA 名即可。
时区不对会导致签到 / 保活等定时任务整体偏移，务必先确认：

```sh
logread -e wb2api | tail -3     # 日志时间应与 `date` 一致
```

### config.json（1.14.0 schema，27 个顶层段）

`accounts` · `admin` · `alerting` · `api_key` · `auth_dir` · `budget` · `cn` · `cooldown` ·
`dns_servers` · `features` · `global` · `listen` · `logging` · `metrics` · `models` · `panel` ·
`pool` · `prompt` · `schedule` · `server` · `session_sticky` · `state_file` · `thinking` ·
`update` · `upstash` · `upstream` · `watchdog`

常用项：

| 字段 | 说明 |
|---|---|
| `listen` | `:7863` 所有网卡，`127.0.0.1:7863` 仅本机（OpenWrt 默认 `0.0.0.0:7863`） |
| `api_key` | 客户端 Bearer Token（装机时随机生成） |
| `auth_dir` / `state_file` | 绝对路径 |
| `server.max_payload_bytes` / `server.shutdown_timeout` | 请求体积上限 / 优雅退出时间 |
| `logging.request_archive_enabled` | 是否把每次请求写进 `data/request-logs/` |
| `logging.panel_log_enabled` / `panel_log_retention_days` / `panel_log_max_mb` | 面板日志开关与容量 |
| `pool.selection_strategy` | 账号选择策略（**1.14 新名**，旧版叫 `pool.strategy`） |
| `pool.max_in_flight` / `max_in_flight_global` | 并发上限，小内存路由调 1~2 |
| `schedule.*` | 签到 / 活跃 / 旅行 / 保活 / 黑猫的整点排程 |
| `thinking.*` | 思考链透传与超时 |
| `budget.*` | 每日额度 / 请求数封顶 |
| `watchdog.*` | 卡死检测与自动重启 |
| `update.auto_enabled` | 自动更新，OpenWrt 上默认关 |
| `upstream.tls_fingerprint` | uTLS 指纹模拟 |
| `upstash.url/token` | 可选，Upstash Redis 做状态镜像（多实例共享） |

旧包（1.13.0）里已移除的字段：`pool.account_order`、`pool.cross_domain_fallback`。

**不要**手改 `pool.strategy`——1.14 只认 `selection_strategy`，写了旧键等价于没配。

改端口后记得同步防火墙：`uci show firewall | grep wb2api_port`。

---

## 7. 服务管理

```sh
/etc/init.d/workbuddy2api start|stop|restart|enable|disable
logread -e workbuddy2api -f
```

init 脚本要点：`START=96`、`USE_PROCD=1`、`respawn 3600 5 0`、`nofile 4096`、
监听地址从 `config.json` 的 `listen` 解析（解析失败回落 7863）。

---

## 8. 从源码构建

### 方式 A：预编译打包（不需要 OpenWrt SDK，推荐）

```sh
./scripts/build-all.sh                      # Linux / macOS
powershell -File scripts\build-all.ps1      # Windows（需 Go + Python）
powershell -File scripts\build-all.ps1 -Version 1.14.0 -SkipPack   # 只编二进制
```

`build-all.ps1` 参数：`-GoRoot`、`-Python`、`-Version`（默认 1.14.0）、`-SkipPack`。
内部固定 `GOOS=linux`、`CGO_ENABLED=0`、`GOFLAGS=-mod=vendor`、`GOTOOLCHAIN=auto`，
产出 7 个二进制到 `prebuilt/`：`mipsle`(softfloat) / `mips`(softfloat) / `armv7` / `armv6` /
`arm64` / `amd64` / `386`，版本串用 `-X main.appVersion=1.14.0` 注入。

单架构打包 + 校验：

```sh
python3 scripts/build-ipk.py --arch aarch64_cortex-a53 \
        --binary prebuilt/wb2api-linux-arm64 --format both --out dist
python3 scripts/verify-ipk.py dist/*.ipk
```

`--format` 取值：`tgz`（24.10+，默认）/ `ar`（≤23.05，文件名带 `-legacy`）/ `both`。
打包固定 `SourceDateEpoch=1735689600`，同输入可复现；`Installed-Size` 自动计算。

`scripts/verify-ipk.py` 逐包校验：容器与 `-legacy` 后缀是否对应、`debian-binary`、control 字段、
`conffiles`、data 清单与文件权限、ELF 的 class / 端序 / `e_machine` 与架构名是否一致、
二进制里是否含 `1.14.0`、`config.default.json` 的覆盖项、`postinst`/`prerm` 的 `sh -n` 语法、
LuCI 包 6 个文件与 `settings.js` 的 `zonename`。
（Windows 上跑要在 PATH 里加 `D:\AI\DSH\toolchain\PortableGit\usr\bin`，否则跳过 `sh -n`。）

### 方式 B：OpenWrt SDK / buildroot 内编译

```sh
./scripts/feeds update packages
./scripts/feeds install golang
cp -r openwrt-wb2api/package/* package/
make menuconfig        # Network -> Web Servers/Proxies -> workbuddy2api
                       # LuCI -> Applications -> luci-app-workbuddy2api
make package/workbuddy2api/compile V=s
make package/luci-app-workbuddy2api/compile V=s
```

`package/workbuddy2api/src/` 已内置上游源码（678 文件）与 `vendor/`（572 文件），编译不联网。
Makefile 里 `GO_PKG_BUILD_FLAGS` 带 `-trimpath -buildvcs=false -mod=vendor`，
`GO_PKG_LDFLAGS` 带 `-s -w -X main.appVersion=$(PKG_VERSION)`。

**SDK 的 golang 必须 ≥ 1.26**（上游 `go.mod` 声明 `go 1.26.10` 且用了新语法）。
24.10 自带 1.22/1.23，会直接报 `go.mod requires go >= 1.26.10`，这种情况走方式 A 用现成 ipk。

---

## 9. 卸载

```sh
opkg remove luci-app-workbuddy2api
opkg remove workbuddy2api
rm -rf /etc/workbuddy2api          # 连同账号凭证一起删，谨慎
```

`conffiles` 保护 `/etc/config/workbuddy2api` 与 `/etc/workbuddy2api/config.default.json`，
卸载时这两项会保留（`.opkg` 后缀备份），重新安装不会丢 UCI 设置。

---

## 10. 常见问题

**Q：`opkg install` 报 `Malformed package file`？**
A：容器格式不对。24.10+ 用不带 `-legacy` 的包，22.03/23.05 用带 `-legacy` 的。

**Q：`/healthz` 返回 503？**
A：账号池没有可用账号时就是 503，加账号后恢复 200。

**Q：LuCI 里看不到菜单？**
A：确认 23.05+，然后 `rm -f /tmp/luci-indexcache* && /etc/init.d/rpcd reload` 再刷新。

**Q：面板能开，接口 401？**
A：请求头 `Authorization: Bearer <api_key>`，key 在 `/etc/workbuddy2api/config.json`。

**Q：改了端口访问不了？**
A：防火墙规则 `Allow-WorkBuddy2API` 的 `dest_port` 同步改，然后 `/etc/init.d/firewall reload`。

**Q：日志时间差 8 小时 / 定时任务时间不对？**
A：时区没生效，见第 6 节。确认 `TZ` 指向的 TZif 存在：
`tr '\0' '\n' < /proc/$(pgrep -f '[w]b2api')/environ | grep TZ`。

**Q：内存吃紧？**
A：调小 `pool.max_in_flight`（1~2）与 `pool.max_in_flight_global`（1），并保持请求归档关闭。

**Q：日志里有 `[updater] GitHub Release 403`？**
A：自动更新检查被 GitHub 限流，`update.auto_enabled=false` 时不影响网关功能。

---

## 11. 目录结构

```
openwrt-wb2api/
├── dist/                          # 32 个预编译 ipk + SHA256SUMS.txt
├── prebuilt/                      # 7 个架构的二进制
├── package/
│   ├── workbuddy2api/             # 主程序包
│   │   ├── Makefile
│   │   ├── files/                 # init / UCI 默认值 / 出厂配置 / uci-defaults / zoneinfo
│   │   └── src/                   # 上游 1.14.0 源码 + vendor（离线编译）
│   └── luci-app-workbuddy2api/    # LuCI 界面包
│       ├── Makefile
│       └── root/                  # menu.d / acl.d / 四个视图
└── scripts/
    ├── build-ipk.py               # ipk 打包器（ar / tar.gz 双格式，可复现）
    ├── gen-default-config.py      # 从上游 config.example.json 生成出厂模板
    ├── verify-ipk.py              # ipk 结构与 ELF 架构校验（32 包全绿）
    ├── build-all.sh / .ps1        # 一键交叉编译 + 打包
    ├── deploy.py                  # SSH/SFTP 一键部署到路由器
    ├── probe-router.py            # 探测目标环境（架构 / 空间 / 已装版本）
    └── diag.py                    # 已安装服务的状态诊断
```

---

## 12. 说明

- 本项目只是上游 `workbuddy2api-panel` 的 OpenWrt 打包层，网关逻辑全部来自上游。
- 凭证以**明文**保存在 `auths/`（目录 700、配置文件 600）。7863 端口只对 LAN 开放，
  不要暴露到公网。
