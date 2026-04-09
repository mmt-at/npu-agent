# v2rayA 处理记录（2026-04-10 UTC）

## 环境

- 系统：Ubuntu 22.04.5 LTS
- 架构：aarch64 / arm64
- 运行特征：环境内没有 `systemd`，`systemctl` 不可用

## 我做了什么

1. 确认了系统环境、包管理器和初始状态。
   - 确认系统为 Ubuntu 22.04 arm64。
   - 确认可用包管理器为 `apt-get`。
   - 确认初始时未安装 `v2raya`。
   - 确认环境中没有 `systemctl`。

2. 按 v2rayA 官网思路尝试接入官方 apt 源。
   - 创建了 `/etc/apt/keyrings`。
   - 下载了 `https://apt.v2raya.org/key/public-key.asc`。
   - 写入了 `/etc/apt/sources.list.d/v2raya.list`。
   - 由于环境缺少 `gpg`，先安装了 `gpg`，并把 key 转成了二进制 keyring。

3. 发现官方 apt 源在当前时间点不可直接使用。
   - `apt-get update` 对 `https://apt.v2raya.org` 返回签名校验失败。
   - 报错为 `NO_PUBKEY 354E516D494EF95F`。
   - 为避免后续 `apt update` 持续报错，我把该源禁用了：
     - `/etc/apt/sources.list.d/v2raya.list.disabled`

4. 改为使用官方 GitHub Release 安装 v2rayA。
   - 查询到 v2rayA 最新 release 为 `2.2.7.5`。
   - 下载并校验了 `installer_debian_arm64_2.2.7.5.deb`。
   - 校验值一致后安装了该 deb 包。

5. 安装了系统仓库里的 `v2ray` 核心作为初始尝试。
   - 当时安装的是 Ubuntu 仓库包 `v2ray 4.34.0-5`。
   - 随后用户在 v2rayA 内连接时报错：
     - `core version too low: the version 4.34.0 is lower than 5.0.0`

6. 处理了 v2rayA 首次启动缺失数据文件的问题。
   - v2rayA 首次启动时缺少：
     - `geoip.dat`
     - `geosite.dat`
   - 我手动下载并放置了这两个文件，使其可以完成初始化。

7. 确认并切换到 v2ray-core v5。
   - 查询到官方 `v2fly/v2ray-core` 最新 arm64 可用 release 为 `v5.47.0`。
   - 下载并校验了 `v2ray-linux-arm64-v8a.zip`。
   - 解压到：
     - `/opt/v2ray-core-v5.47.0`
   - 验证版本输出为：
     - `V2Ray 5.47.0`

8. 重新启动 v2rayA，并强制指定它使用 v5 核心。
   - 启动命令实际为：
     - `/usr/bin/v2raya --config /etc/v2raya --v2ray-bin /opt/v2ray-core-v5.47.0/v2ray --v2ray-assetsdir /opt/v2ray-core-v5.47.0 --log-file /var/log/v2raya/v2raya.log --log-disable-timestamp`
   - 从日志确认：
     - `V2Ray binary is /opt/v2ray-core-v5.47.0/v2ray`
     - `V2Ray 5.47.0 started`

9. 彻底移除了旧的 v2ray 4.x。
   - 执行了 `apt-get purge -y v2ray`。
   - 现在系统中 `command -v v2ray` 已无输出。
   - 这样可以避免 v2rayA 再误用旧版核心。

## 当前状态

- v2rayA 已安装：`2.2.7.5`
- v2ray-core v5 已安装：`/opt/v2ray-core-v5.47.0/v2ray`
- 旧的 `v2ray 4.34.0` 已移除
- v2rayA Web UI 可访问：`http://127.0.0.1:2017`
- 当前本地代理端口：
  - HTTP: `127.0.0.1:20171`
  - SOCKS5: `127.0.0.1:20170`
- 配置目录：
  - `/etc/v2raya`
- 日志文件：
  - `/var/log/v2raya/v2raya.log`

## 当前实际启动方式

- 当前不是通过 `systemd` 启动。
- 当前是直接以前台命令启动：
  - `/usr/bin/v2raya --config /etc/v2raya --v2ray-bin /opt/v2ray-core-v5.47.0/v2ray --v2ray-assetsdir /opt/v2ray-core-v5.47.0 --log-file /var/log/v2raya/v2raya.log --log-disable-timestamp`
- 这会再由 v2rayA 拉起核心进程：
  - `/opt/v2ray-core-v5.47.0/v2ray run --config=/etc/v2raya/config.json`

## 这种启动方式的影响

- 这种方式本质上依赖于启动它的终端会话。
- 如果终端会话结束、TTY 被关闭、上层会话管理器回收该会话，v2rayA 进程通常也会退出。
- 在这次环境里，我已经观察到：
  - 早先几次后台拉起的 v2rayA 进程在会话结束后没有持续存活。
- 原因不是 v2rayA 本身，而是当前环境没有独立的服务管理器来托管它。

## 如果关闭所有 shell，是否会退出

- 按当前启动方式：有较大概率会退出。
- 如果你需要“退出所有 shell 仍然运行”，应该改成由独立 supervisor 托管，而不是仅靠当前这个前台命令。

## 可行的持久运行方式

### 1. 最推荐：systemd

- 适用前提：系统存在 `systemd` 且 `systemctl` 可用。
- 优点：开机自启、退出 shell 不受影响、日志和重启策略都比较标准。
- 当前环境不适用，因为这里没有 `systemd`。

### 2. 推荐：supervisor / runit / s6

- 适用前提：你所在机器有这些进程管理器之一。
- 优点：退出 shell 后仍可运行，且比 `nohup` 稳定。
- 这是当前这类“无 systemd 环境”里更稳的方案。

### 3. 临时可用：tmux / screen

- 适用前提：安装了 `tmux` 或 `screen`。
- 优点：实现简单。
- 缺点：本质上仍然是会话托管，不如真正的 supervisor 标准。
- 示例：
  - `tmux new -s v2raya`
  - 在 tmux 里运行当前启动命令
  - 退出时按 `Ctrl-b d`

### 4. 最弱：nohup + setsid

- 优点：简单。
- 缺点：在某些容器、受限终端、多层会话代理环境下并不可靠。
- 这次环境中我已经遇到过类似不稳定表现，因此不建议把它当最终方案。

## 当前代理变量应该怎么设置

- HTTP 代理端口：`127.0.0.1:20171`
- SOCKS5 代理端口：`127.0.0.1:20170`

推荐设置：

```bash
export http_proxy=http://127.0.0.1:20171
export https_proxy=http://127.0.0.1:20171
export HTTP_PROXY=http://127.0.0.1:20171
export HTTPS_PROXY=http://127.0.0.1:20171
export all_proxy=socks5://127.0.0.1:20170
export ALL_PROXY=socks5://127.0.0.1:20170
export no_proxy=127.0.0.1,localhost
export NO_PROXY=127.0.0.1,localhost
```

说明：

- 一般应用优先使用 `http_proxy` / `https_proxy`。
- 需要 SOCKS5 的程序可使用 `all_proxy`。
- `no_proxy` 用于避免本地请求再走代理。

## 过程记录是否充分

- 如果目标只是“说明我做过哪些关键操作、遇到什么问题、最终状态是什么”，当前记录已经充分。
- 如果目标是“别人拿到文档后要完整复现整个过程”，原始版本还不够充分。
- 本次补充后，文档已经覆盖了：
  - 初始环境
  - 每一步主要动作
  - 为什么放弃官方 apt 源
  - 为什么要切换到 v5
  - 当前实际启动命令
  - 这种启动方式的局限
  - 持久运行的可选方案
  - 当前代理端口和环境变量
- 如果你还要把它变成“完全可复现的操作手册”，还应再补一版：
  - 每条实际执行过的命令清单
  - 每步执行前后的验证输出
  - 适用于 `systemd` 和非 `systemd` 两种环境的标准启动脚本

## 关于 IDE 端口转发的额外观察

- 这是本次排查过程中，用户侧观察到的现象，不是 v2rayA 官方机制说明。
- 现象描述：
  - 即使 `v2raya` 已经成功启动并监听 `2017`，IDE 侧有时不会立刻自动 forward 该端口。
  - 但一旦命令行里出现监听信息，或者终端/输出中出现了类似 `127.0.0.1:2017`、`http://127.0.0.1:2017` 这样的地址，IDE 可能就会触发端口识别和转发。
- 这更像是 IDE 的端口探测或地址识别行为，而不是 v2rayA 本身“是否监听成功”的差异。
- 因此要区分两件事：
  - 服务是否真的已经在主机上监听端口
  - IDE 是否已经识别并 forward 这个端口
- 在这次问题里，用户的判断是：
  - 有时候服务已经起来了，但 IDE 还没 forward
  - 在终端恢复、输出刷新、或出现地址文本后，IDE 才开始 forward
- 这说明“能否在 IDE 里点开端口”不应作为唯一判断依据。
- 更可靠的判断方式仍然是：
  - `ps -ef | grep '[v]2raya'`
  - `netstat -ltnp | grep ':2017 '`
  - `curl http://127.0.0.1:2017/`

## 已观察到的环境限制

- 当前环境没有 `systemd`，因此不能使用 `systemctl enable --now v2raya` 这种标准持久化方式。
- 当前环境里尝试启用透明代理时会失败，因为缺少或不支持这些系统能力：
  - `iptables-legacy`
  - `ip`
  - OS 级 system proxy 配置能力

## 这次操作中改动过的系统位置

- `/etc/apt/keyrings`
- `/etc/apt/sources.list.d/v2raya.list.disabled`
- `/etc/default/v2raya`
- `/etc/v2raya`
- `/usr/bin/v2raya`
- `/opt/v2ray-core-v5.47.0`
- `/var/log/v2raya`
- `/root/.local/share/v2ray`
