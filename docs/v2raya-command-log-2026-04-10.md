# v2rayA 命令级记录（2026-04-10 UTC）

## 说明

- 本文档记录的是这次处理过程中实际执行过的关键命令、执行目的和主要结果。
- 这是一份整理版记录，不是逐字逐行的原始终端转储。
- 为了可读性，省略了重复轮询、长时间下载进度、无信息量的空输出和部分辅助检查。

## 1. 初始环境确认

### 命令

```bash
uname -a
cat /etc/os-release
command -v v2raya || true
command -v apt-get || command -v dnf || command -v yum || command -v pacman || true
systemctl is-active v2raya || true
id -u
```

### 目的

- 确认操作系统、架构、包管理器、当前用户权限、`v2raya` 是否已安装、`systemd` 是否可用。

### 结果

- 系统为 Ubuntu 22.04.5 LTS。
- 架构为 arm64 / aarch64。
- 包管理器为 `apt-get`。
- 当前用户是 `root`。
- `v2raya` 初始未安装。
- `systemctl` 不可用，说明当前环境没有可直接使用的 `systemd`。

## 2. 尝试接入 v2rayA 官方 apt 源

### 命令

```bash
install -d /etc/apt/keyrings
curl -fsSL https://apt.v2raya.org/key/public-key.asc -o /etc/apt/keyrings/v2raya.asc
bash -lc "printf 'deb [signed-by=/etc/apt/keyrings/v2raya.asc] https://apt.v2raya.org/ v2raya main\n' > /etc/apt/sources.list.d/v2raya.list"
apt-get update
```

### 目的

- 按官网方式接入官方 apt 源，直接通过系统包管理器安装 `v2raya`。

### 结果

- 初次 `apt-get update` 失败。
- 主要报错为：
  - `Unknown error executing apt-key`
  - 仓库签名校验失败。

## 3. 补装 gpg 并重试 apt 源

### 命令

```bash
apt-get install -y gpg
gpg --dearmor -o /etc/apt/keyrings/v2raya.gpg /etc/apt/keyrings/v2raya.asc
bash -lc "printf 'deb [signed-by=/etc/apt/keyrings/v2raya.gpg] https://apt.v2raya.org/ v2raya main\n' > /etc/apt/sources.list.d/v2raya.list"
apt-get update
```

### 目的

- 让 apt 能正确读取仓库 key，并再次验证官方源是否可用。

### 结果

- `gpg` 安装成功。
- key 已成功转换为二进制 keyring。
- 但再次 `apt-get update` 仍失败，报错：
  - `NO_PUBKEY 354E516D494EF95F`
- 结论：这次环境下官方 apt 源没有继续使用。

## 4. 改为使用 GitHub Release 安装 v2rayA

### 命令

```bash
curl -fsSL https://api.github.com/repos/v2rayA/v2rayA/releases/latest
curl -fL https://github.com/v2rayA/v2rayA/releases/download/v2.2.7.5/installer_debian_arm64_2.2.7.5.deb -o /tmp/installer_debian_arm64_2.2.7.5.deb
curl -fL https://github.com/v2rayA/v2rayA/releases/download/v2.2.7.5/installer_debian_arm64_2.2.7.5.deb.sha256.txt -o /tmp/installer_debian_arm64_2.2.7.5.deb.sha256.txt
sha256sum /tmp/installer_debian_arm64_2.2.7.5.deb
cat /tmp/installer_debian_arm64_2.2.7.5.deb.sha256.txt
```

### 目的

- 获取官方最新 release。
- 下载 Debian arm64 安装包并做校验。

### 结果

- 确认最新 release 为 `v2.2.7.5`。
- `.deb` 包下载成功。
- SHA256 校验值一致。

## 5. 安装 v2rayA 和初始 core

### 命令

```bash
apt-cache policy v2ray xray
apt-get install -y v2ray /tmp/installer_debian_arm64_2.2.7.5.deb
command -v v2raya
command -v v2ray
v2raya --help | sed -n '1,120p'
dpkg -L v2raya | sed -n '1,160p'
sed -n '1,200p' /lib/systemd/system/v2raya.service
sed -n '1,200p' /etc/default/v2raya
```

### 目的

- 安装 `v2rayA` 和初始可用的 `v2ray` core。
- 查看安装路径、服务定义和默认配置。

### 结果

- 成功安装：
  - `v2raya 2.2.7.5`
  - `v2ray 4.34.0-5`
- 安装脚本尝试调用 `systemctl`，但当前环境没有 `systemd`。
- 确认 `v2raya` 可执行文件位于 `/usr/bin/v2raya`。

## 6. 禁用失效 apt 源并准备手工启动

### 命令

```bash
mv /etc/apt/sources.list.d/v2raya.list /etc/apt/sources.list.d/v2raya.list.disabled
install -d /etc/v2raya /var/log/v2raya
```

### 目的

- 避免后续 `apt update` 因失效仓库继续报错。
- 创建配置目录和日志目录，便于手工启动。

### 结果

- 官方 apt 源已禁用。
- 运行所需目录已就位。

## 7. 首次手工启动 v2rayA 并观察失败原因

### 命令

```bash
bash -lc 'nohup env V2RAYA_CONFIG=/etc/v2raya V2RAYA_LOG_FILE=/var/log/v2raya/v2raya.log /usr/bin/v2raya --log-disable-timestamp >/var/log/v2raya/launch.out 2>&1 & echo $!'
ps -p <pid> -o pid,ppid,user,etime,cmd
sed -n '1,120p' /var/log/v2raya/v2raya.log
tail -n 80 /var/log/v2raya/v2raya.log
ls -la /root/.local/share/v2ray 2>/dev/null || true
```

### 目的

- 在没有 `systemd` 的环境里尝试手工拉起 `v2raya`。
- 确认失败点。

### 结果

- 首次启动未能稳定跑起来。
- 日志显示缺少数据文件：
  - `geoip.dat`
  - `geosite.dat`

## 8. 手动补齐 geo 数据文件

### 命令

```bash
curl -fL https://github.com/v2fly/geoip/releases/latest/download/geoip.dat -o /root/.local/share/v2ray/geoip.dat
curl -fL https://github.com/v2fly/domain-list-community/releases/latest/download/dlc.dat -o /root/.local/share/v2ray/geosite.dat
```

### 目的

- 解决首次启动缺少 `geoip.dat` / `geosite.dat` 的问题。

### 结果

- 两个数据文件下载成功并放置到 `v2rayA` 查找的位置。

## 9. 以前台方式启动 v2rayA 并验证 Web UI

### 命令

```bash
/usr/bin/v2raya --config /etc/v2raya --v2ray-assetsdir /root/.local/share/v2ray --log-file /var/log/v2raya/v2raya.log --log-disable-timestamp
netstat -ltnp 2>/dev/null | grep ':2017 ' || true
curl -sI --max-time 5 http://127.0.0.1:2017 | sed -n '1,10p'
curl -s --max-time 5 http://127.0.0.1:2017/ | sed -n '1,20p'
grep -n 'V2Ray binary is\|V2Ray asset directory is\|Version:' /var/log/v2raya/v2raya.log | tail -n 10
```

### 目的

- 让 `v2rayA` 真正监听起来。
- 验证 Web UI 是否已提供服务。

### 结果

- `v2rayA` 成功监听 `2017`。
- `GET /` 能返回 Web UI HTML。
- 但此时它使用的 core 仍是 `/usr/bin/v2ray`，版本为 `4.34.0`。

## 10. 发现 core 版本过低

### 命令

```bash
tail -n 80 /var/log/v2raya/v2raya.log
```

### 目的

- 查看用户反馈的连接失败原因。

### 结果

- 日志出现：
  - `core version too low: the version 4.34.0 is lower than 5.0.0`
- 说明需要切换到 v2ray-core v5。

## 11. 下载并校验官方 v2ray-core v5

### 命令

```bash
curl -fsSL https://api.github.com/repos/v2fly/v2ray-core/releases/latest | grep -o 'https://[^"[:space:]]*v2ray-linux-arm64[^"[:space:]]*\.zip' | sort -u
apt-get install -y unzip
curl -fL https://github.com/v2fly/v2ray-core/releases/download/v5.47.0/v2ray-linux-arm64-v8a.zip -o /tmp/v2ray-linux-arm64-v8a-v5.47.0.zip
curl -fL https://github.com/v2fly/v2ray-core/releases/download/v5.47.0/v2ray-linux-arm64-v8a.zip.dgst -o /tmp/v2ray-linux-arm64-v8a-v5.47.0.zip.dgst
cat /tmp/v2ray-linux-arm64-v8a-v5.47.0.zip.dgst
sha256sum /tmp/v2ray-linux-arm64-v8a-v5.47.0.zip
```

### 目的

- 获取官方 v5 core。
- 下载并校验 arm64 压缩包。

### 结果

- 确认使用 `v5.47.0`。
- ZIP 文件下载成功。
- SHA256 与 digest 文件一致。

## 12. 解压 v5 core 并确认版本

### 命令

```bash
install -d /opt/v2ray-core-v5.47.0
unzip -o /tmp/v2ray-linux-arm64-v8a-v5.47.0.zip -d /opt/v2ray-core-v5.47.0
chmod 755 /opt/v2ray-core-v5.47.0/v2ray
/opt/v2ray-core-v5.47.0/v2ray version
ls -la /opt/v2ray-core-v5.47.0
```

### 目的

- 安装独立的 v5 core，不覆盖系统路径。
- 验证二进制版本。

### 结果

- v5 core 解压到 `/opt/v2ray-core-v5.47.0`。
- `v2ray version` 输出为 `V2Ray 5.47.0`。

## 13. 用 v5 core 重启 v2rayA

### 命令

```bash
/usr/bin/v2raya --config /etc/v2raya --v2ray-bin /opt/v2ray-core-v5.47.0/v2ray --v2ray-assetsdir /opt/v2ray-core-v5.47.0 --log-file /var/log/v2raya/v2raya.log --log-disable-timestamp
tail -n 40 /var/log/v2raya/v2raya.log
netstat -ltnp 2>/dev/null | grep ':2017 ' || true
curl -s --max-time 5 http://127.0.0.1:2017/ | sed -n '1,20p'
tail -n 80 /var/log/v2raya/v2raya.log
```

### 目的

- 让 `v2rayA` 明确使用 v5 core。
- 确认 Web UI 和 core 已恢复正常。

### 结果

- 日志明确显示：
  - `V2Ray binary is /opt/v2ray-core-v5.47.0/v2ray`
  - `V2Ray 5.47.0 started`
- `2017` 端口可监听。
- Web UI 正常响应。

## 14. 移除旧的 v2ray 4.x

### 命令

```bash
apt-get purge -y v2ray
command -v v2ray || true
```

### 目的

- 避免 `v2rayA` 后续误用旧的 `4.34.0` core。

### 结果

- `v2ray 4.34.0-5` 已彻底移除。
- `command -v v2ray` 无输出。

## 15. 确认当前端口和代理入口

### 命令

```bash
sed -n '1,240p' /etc/v2raya/config.json
netstat -ltnp 2>/dev/null | grep -E ':(2017|20170|20171|1080|10808|10809|1081|10810) ' || true
```

### 目的

- 确认 v2rayA 当前生成的本地代理端口。

### 结果

- Web UI:
  - `127.0.0.1:2017`
- SOCKS5:
  - `127.0.0.1:20170`
- HTTP:
  - `127.0.0.1:20171`

## 16. 观察到的运行期限制

### 命令

```bash
tail -n 20 /var/log/v2raya/v2raya.log
```

### 目的

- 检查运行中是否还有环境相关报错。

### 结果

- 观察到透明代理和系统代理相关报错：
  - 缺少 `iptables-legacy`
  - 缺少 `ip`
  - OS 不支持自动 system proxy 配置
- 结论：
  - 当前环境下适合使用显式 `http_proxy` / `https_proxy` / `all_proxy`
  - 不适合依赖 transparent proxy 或 system proxy 自动接管

## 当前关键路径

- v2rayA:
  - `/usr/bin/v2raya`
- v2ray-core v5:
  - `/opt/v2ray-core-v5.47.0/v2ray`
- 配置目录:
  - `/etc/v2raya`
- 日志:
  - `/var/log/v2raya/v2raya.log`
- Web UI:
  - `http://127.0.0.1:2017`
- HTTP 代理:
  - `http://127.0.0.1:20171`
- SOCKS5 代理:
  - `socks5://127.0.0.1:20170`
