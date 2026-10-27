# wifi-panel

![docker](https://github.com/wodty/wifi-panel/actions/workflows/docker.yml/badge.svg)

**把手机浏览器变成电脑的鼠标键盘，同时当电视遥控器用。** 面板上的按钮位置、大小、颜色、动作全部自定义——想做成游戏手柄、电视遥控，还是办公快捷键板，都随你。

中枢跑在 NAS / 服务器的 Docker 里，电脑上只装一个几百 KB 的 Agent，手机上什么都不用装（浏览器打开即用）。

![界面预览](docs/preview.png)

---

## 特性

- **可编程面板**：按钮自由拖放定位、调整大小与配色，动作支持键盘单击 / 按住持续 / 组合键、鼠标左中右键、系统媒体键、电视按键、电视启动应用。
- **触控板手势**：单指滑动移动鼠标，轻点左键，双指滑动滚轮，双指轻点右键。
- **5 种内置模板**：通用 / 游戏手柄 / 媒体控制 / 电视遥控 / 空白。首次启动自动生成一个「通用」默认面板，打开就能用。
- **电视多协议**：Android TV 系走 ADB，三星 Tizen 与 LG webOS 走各自的原生 WebSocket 协议，主流品牌基本覆盖。
- **不依赖 PC 开机控电视**：电视指令由中枢（NAS 上）直接执行，电脑关着也能用手机换台、调音量。
- **PC 端零端口**：Agent 主动外连中枢，电脑不用开端口、不用动防火墙，放在任何内网机器上都能接。
- **多电脑多电视**：几台电脑、几台电视各起一个名字，面板顶部随时切换控制目标；也可以一键广播——「关掉所有电视」「所有电脑静音」。
- **防按键卡死**：手机断线、切后台、来电话时，中枢会释放该设备按住的全部按键，不会出现「一直往前走」。
- **安卓 App**：可选安装。WebView 壳 + 记住中枢地址、屏幕常亮、切后台自动断开，面板页面仍然由中枢托管，升级中枢 App 不用重装。
- **零前端依赖**：手机端是原生 JS 单页，无需构建、无需安装 App。

## 工作原理

```
手机浏览器 ──WebSocket──▶ 中枢（NAS · Docker） ──┬── ADB / SSAP / Tizen ──▶ 电视
                       网页 + 布局存储 + 转发    └── WebSocket 回连 ──▶ PC Agent（注入鼠标键盘）
```

- **中枢**（`server/`）：FastAPI + WebSocket。托管网页、存储面板配置、把手机指令转发给 Agent，电视指令本地执行。
- **PC Agent**（`agent/`）：主动外连中枢，用 pynput 注入鼠标键盘事件。Windows / macOS / Linux(X11) 通用。
- **网页**（`web/`）：面板列表、编辑器、使用模式、电视设置，原生 JS 零依赖。

## 支持的设备

| 设备 | 说明 |
|------|------|
| 中枢 | 任何能跑 Docker 的机器（群晖 / 威联通 / Unraid / x86 小主机 / 树莓派），或直接跑 Python 的电脑 |
| 电脑（被控） | Windows、macOS、Linux（X11 桌面） |
| 手机（控制） | iOS / Android 的现代浏览器，同一局域网 |
| 电视 · ADB | 小米、TCL / 雷鸟、海信、创维 / 酷开、索尼、长虹、康佳等 Android TV 系 |
| 电视 · 三星 | Tizen 系统的三星智能电视 |
| 电视 · LG | webOS（2014 及以后） |

不支持：华为智慧屏（鸿蒙，协议封闭）、Apple TV（需专用协议）。

---

## 安装

### 前置条件

- 一台常开的机器跑中枢（NAS / 小主机 / 电脑），与手机、电视在同一局域网
- 中枢端口默认 `8765`
- 想控电脑的话，电脑上需要 Python 3.9+

---

### 一、中枢：Docker 部署（推荐）

镜像已发布在 GitHub Container Registry，支持 `linux/amd64` 与 `linux/arm64`（群晖 / 威联通 / x86 小主机 / ARM 板子都能跑），内置 `adb`，电视控制开箱可用。

```bash
git clone https://github.com/wodty/wifi-panel.git
cd wifi-panel
```

先设令牌，再启动：

```bash
# 方式 A：写进 .env（推荐，compose 会自动读取）
echo "PANEL_TOKEN=你的密码" > .env
docker compose up -d

# 方式 B：不用 .env，直接改 docker-compose.yml 里的 PANEL_TOKEN
```

升级到最新版本：

```bash
docker compose pull && docker compose up -d
```

面板配置、电视 IP、ADB 配对密钥都存在 `server/storage/`（已挂载为卷），升级重建容器不会丢。

<details>
<summary>不用 clone 仓库，最小启动</summary>

把下面内容存成 `docker-compose.yml`，同目录执行 `docker compose up -d`：

```yaml
services:
  panel:
    image: ghcr.io/wodty/wifi-panel:latest
    container_name: wifi-panel
    ports: ["8765:8765"]
    environment:
      - PANEL_TOKEN=你的密码
    volumes:
      - ./server/storage:/app/server/storage
    restart: unless-stopped
```

若拉取时报 `denied`，说明镜像包还是私有的，先 `docker login ghcr.io`（用户名 GitHub 账号，密码用 PAT）。
</details>

<details>
<summary>群晖 / 威联通用户</summary>

图形界面里新建「项目 / 应用」，镜像填 `ghcr.io/wodty/wifi-panel:latest`，端口映射 `8765`，目录映射 `server/storage`，环境变量填 `PANEL_TOKEN` 即可；也可以直接用本仓库的 `docker-compose.yml`。
</details>

<details>
<summary>自己构建镜像（改了代码）</summary>

```bash
docker compose build && docker compose up -d
```
（把 `docker-compose.yml` 里的 `image:` 注释掉、放开 `build: .`，或直接 `docker build -t wifi-panel .`）
</details>

---

### 镜像标签说明

| 标签 | 含义 |
|------|------|
| `latest` | 跟随 `main` 分支最新提交 |
| `1.0.0` / `1.0` | 打 `v1.0.0` 这类 git tag 时自动生成 |
| `sha-xxxxxxx` | 某次提交的精确版本，适合锁定部署 |

镜像构建与自动化测试由 GitHub Actions 完成（`.github/workflows/docker.yml`）。

---

### 二、中枢：直接跑 Python（不需要 Docker）

```bash
git clone https://github.com/wodty/wifi-panel.git
cd wifi-panel
pip install -r requirements.txt
```

Windows 用户可以直接双击 `start_hub.bat`——它会自动建虚拟环境、装依赖再启动。

手动启动：

```bash
# Windows
set PANEL_TOKEN=你的密码
python -m uvicorn server.main:app --host 0.0.0.0 --port 8765

# macOS / Linux
PANEL_TOKEN=你的密码 python -m uvicorn server.main:app --host 0.0.0.0 --port 8765
```

> 电视控制需要系统里有 `adb` 命令：Windows 装 [platform-tools](https://developer.android.com/tools/releases/platform-tools)，Debian/Ubuntu `apt install adb`，macOS `brew install android-platform-tools`。只用电脑控制则无需安装。

---

### 三、电脑端 Agent（需要控电脑鼠标键盘时）

中枢所在机器和被控电脑不是同一台时，在被控电脑上执行：

```bash
pip install -r agent/requirements.txt
python agent/agent.py ws://<中枢IP>:8765/ws/agent <你的密码> --name 客厅主机
```

- `--name` 是这台电脑在手机上显示的名字（默认取主机名），建议每台电脑起不一样的名字
- 设备 id 首次运行自动生成，存在 `agent/.agent_id`，重启不变；想换一台“身份”删掉这个文件即可
- Windows 可直接双击 `agent/start_agent.bat`（**先在文件开头把 `HUB` / `TOKEN` / `NAME` 改好**）

**Windows 开机自启（后台无窗口）**

先双击 `agent/start_agent.bat` 调试，确认能连上、能控鼠标键盘，再配自启。

*方式 A · 计划任务（推荐）*：编辑好 `start_agent.bat` 后，右键「以管理员身份运行」`agent/install_autostart.bat`。它注册一个登录时触发的计划任务，通过 `start_agent_hidden.vbs` 静默拉起 Agent——无黑窗口、不弹框。卸载运行 `agent/uninstall_autostart.bat`。

*方式 B · 启动文件夹*：`Win + R` 输入 `shell:startup` 回车，把 `agent/start_agent_hidden.vbs` 的快捷方式放进去。效果与方式 A 相同，随当前用户登录启动。

*方式 C · 注册成 Windows 服务（NSSM）*：服务在登录前就能启动、崩溃自动拉起，适合常驻。但注意：**Agent 不适合用服务方式跑**——Windows 服务运行在 Session 0，碰不到你桌面会话的鼠标键盘，注入会静默失效。服务方式适合跑的是「中枢」：

```text
# 管理员命令行，nssm 从 https://nssm.cc 下载后加入 PATH
nssm install wifi-panel-hub "C:\wifi-panel\.venv\Scripts\python.exe" "-m uvicorn server.main:app --host 0.0.0.0 --port 8765"
nssm set wifi-panel-hub AppDirectory "C:\wifi-panel"
nssm set wifi-panel-hub AppEnvironmentExtra PANEL_TOKEN=你的密码
nssm start wifi-panel-hub
rem 卸载：nssm stop wifi-panel-hub && nssm remove wifi-panel-hub confirm
```

**权限说明**

- macOS：首次运行需在「系统设置 → 隐私与安全性 → 辅助功能」里授权终端 / Python。
- Linux：X11 桌面可直接用；Wayland 会话下 pynput 无法注入输入事件，需切换到 X11 登录。

---

### 四、手机端

两种用法，选一个就行。

**方式 A · 浏览器（零安装）**

1. 手机连上同一 WiFi
2. 浏览器打开 `http://<中枢IP>:8765`
3. 输入令牌，连接

连接页可以手动填中枢地址（`IP:端口`），留空则连当前页面所在的中枢——页面放在哪都能指到别处的中枢。也支持带参数免输入：`http://<中枢IP>:8765/?host=<中枢IP>:8765&token=<令牌>`，存成书签下次一键进面板。

**方式 B · 安卓 App（可选）**

从 [Releases](https://github.com/wodty/wifi-panel/releases) 下载 `wifi-panel-*.apk` 安装。第一次打开填中枢地址和令牌，之后自动连接、记住配置。相比浏览器多了：

- 打开即进面板，不用每次输地址、点连接
- 屏幕常亮，当遥控器用不会中途熄屏
- 切后台 / 锁屏自动断开连接，中枢立刻释放按住的按键（不会「一直往前走」），回来自动重连
- 返回键或长按屏幕：重新加载、修改中枢地址、退出

App 只是个 WebView 壳，不打包面板页面——中枢升级了新功能，App 不用重装。APK 由 GitHub Actions 自动构建（`.github/workflows/android.yml`），打 `v*` 标签发布 Release 时会自动附上 APK。

列表里已有一个「通用」默认面板：触控板 + 鼠标三键 + PC 常用键 + 电视遥控区（方向环 / OK / 返回 / 桌面 / 音量），点「使用」就能同时控制电脑和电视；点「编辑」可以改按钮，或点「+ 新建面板」从模板开始。

> 想把网页加到主屏幕全屏使用（PWA），需要 HTTPS（局域网 `http://IP` 属于非安全上下文）。可用 Tailscale 或自建内网域名 + 证书；或者直接用上面的 App，没有这个限制。

---

### 五、电视端

手机上面板列表右上角「设备」→「+ 添加电视」→ 选协议 → 填电视 IP（端口自动带出）→ 保存 → 点「测试」连接。然后新建「电视遥控」模板面板。

**ADB 系（小米 / TCL·雷鸟 / 海信 / 创维 / 索尼 / 长虹 / 康佳）**

1. 电视：设置 → 关于 → 连点「软件版本」7 次，开启开发者模式
2. 开发者选项 → 打开「网络调试 / USB 调试（网络）」
3. 中枢点「连接测试」，电视上弹出授权框，勾选「一律允许」

**三星 Tizen**：首次连接电视会弹出「允许」，确认即可，令牌自动保存。

**LG webOS**：首次连接电视屏幕弹出「允许」，确认后配对密钥自动保存。

> 电视控制的安全性：ADB 端口长期开放存在被内网其他设备利用的风险。建议在路由器上只允许中枢 IP 访问电视对应端口，或不用时关闭网络调试。

---

### 六、多台电脑 / 多台电视

**加设备**：面板列表右上角「设备」——电脑装好 Agent 会自动出现（点「改名」起个好认的名字）；电视点「+ 添加电视」，有几台加几台，每台各自的协议、IP、配对凭证独立保存，两台三星 / 两台 LG 互不干扰。

**控制谁**：打开任一面板，顶部有两个下拉：

- 「电脑」「电视」默认是「自动」——各挑第一台在线的设备
- 随时切换成指定设备，比如面板不动、把电视从客厅切到卧室
- 选「全部电脑 / 全部电视」就是广播：一条「电源」关掉所有电视，一条「静音」全屋静音

**记住绑定**：编辑模式下顶栏会出现「设为默认」，把当前选择存成这个面板的默认目标——给每个房间各复制一份面板，客厅面板管客厅、卧室面板管卧室。

**单键跨设备**：编辑器里选中任意按钮，有个「目标设备」下拉，可以让某一个键固定打到指定设备——比如客厅面板里放一个「卧室电视电源」。

**迁移**：老版本的单电视配置会在升级后自动变成设备表里的第一台，老面板、旧书签全部照常可用，不用做任何事。

---

## 配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `PANEL_TOKEN` | `panel123` | 访问令牌，网页与 Agent 共用。**部署前务必修改** |
| `PANEL_PORT` | `8765` | 以 `python -m server.main` 方式启动时的监听端口 |

## 常见问题

**手机打不开页面？**
确认手机和中枢在同一 WiFi；用中枢机器的局域网 IP（不是 `127.0.0.1`）；中枢机器防火墙放行 8765。

**按按钮电脑没反应？**
页面右上角有连接状态点：灰点表示 Agent 未连接。检查 Agent 是否在运行、令牌是否与中枢一致、Agent 里的中枢地址是否正确。

**电视连接失败？**
电视网络调试未开、IP 变了（建议在路由器固定 IP）、或首次授权没点「一律允许」。ADB 授权异常时可删除 `server/storage/adb_key` 后重新连接。

**电视按键无效但显示已连接？**
电视可能处于待机，先按「唤醒」。

**Ctrl / Shift 之类的键按了不放开？**
不会出现。手机断开连接时中枢会释放该设备的全部按键；如遇异常，重启 Agent 即可。

## 目录结构

```
wifi-panel/
├── server/                 # 中枢：FastAPI + WebSocket
│   ├── main.py             #   路由、多设备中继、断线释放
│   ├── devices.py          #   设备表（多台电脑 / 多台电视的注册与迁移）
│   ├── templates.py        #   内置面板模板（唯一数据源）
│   ├── tv.py               #   多电视管理（分发、每台一把锁、状态缓存）
│   ├── tv_adb.py           #   ADB 后端
│   ├── tv_samsung.py       #   三星 Tizen 后端
│   ├── tv_lg.py            #   LG webOS 后端
│   └── storage/            #   面板配置 / 设备表 / 电视密钥（运行时生成）
├── agent/agent.py          # 被控电脑上的输入注入 Agent
├── web/                    # 手机端网页（原生 JS）
├── tests/                  # 冒烟测试 + 多设备测试
├── Dockerfile
├── docker-compose.yml
├── start_hub.bat                    # Windows 一键启动中枢
├── agent/start_agent.bat            # Windows 一键启动 Agent（前台调试）
├── agent/start_agent_hidden.vbs     # Agent 静默启动（无窗口）
└── agent/install_autostart.bat      # 注册开机自启计划任务
```

## 许可

MIT
