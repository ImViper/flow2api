# Windows 远端电脑最简部署

本文档面向只部署 `flow2api` 的场景：远端是一台可远程桌面登录的 Windows 电脑，不部署 `qiyuan-api`，先自己使用，尽量少组件。

## 结论

可以把当前项目打成压缩包带到远端，但不是“解压后双击就能用”。远端仍然需要：

- 安装 Python 3.10+。
- 安装 Python 依赖。
- 安装并登录 BitBrowser。
- 在远端确认 Flow/Google 登录态可用。
- 按远端实际窗口 ID 绑定 BitBrowser 窗口。

不要把 `.venv` 一起打包。Python 虚拟环境通常包含本机绝对路径和平台状态，直接复制到另一台 Windows 电脑上不可靠。

## 远端准备

远端 Windows 电脑需要：

- 可用的远程桌面会话。
- Python 3.10 或 3.11，安装时勾选 `Add python.exe to PATH`。
- BitBrowser 客户端。
- 能访问 Google/Flow 的网络环境和代理。
- Windows 防火墙放行 Flow2API 端口，例如 `8000`。

如果只给自己访问，可以先直接开放 `8000`。如果更谨慎，防火墙只允许你的本机公网 IP 访问 `8000`。

不要放行 BitBrowser 本地 API 端口 `54345`，它只应该被本机访问。

## BitBrowser 同账号说明

远端可以登录你现在使用的同一个 BitBrowser 账号。

但要注意：

- BitBrowser 账号相同，不代表本地所有窗口状态一定完整同步到远端。
- 如果窗口环境同步到了远端，打开对应窗口，确认 Flow/Google 已登录即可。
- 如果没有同步，远端需要新建或重新登录浏览器窗口。
- Flow2API 里绑定的是远端实际的 `BitBrowser 窗口 ID`，不一定和本地窗口 ID 一样。
- 不建议本地和远端同时操作同一个 Google/Flow 账号窗口，容易引发账号状态混乱或风控。

最稳流程是：远端登录 BitBrowser 账号，打开目标窗口，访问 Flow 确认可用，然后把远端窗口 ID 填进 Flow2API 的 Token 配置。

## 本地打包

在本地项目目录运行：

```powershell
cd H:\Code\flow2api

$pkg = "flow2api-windows-package"
Remove-Item -Recurse -Force $pkg, "$pkg.zip" -ErrorAction SilentlyContinue
New-Item -ItemType Directory $pkg | Out-Null

Copy-Item src, static, config, docs, scripts -Destination $pkg -Recurse
Copy-Item main.py, requirements.txt, README.md, API_DOCS.md, LICENSE -Destination $pkg

Compress-Archive -Path "$pkg\*" -DestinationPath "$pkg.zip" -Force
```

生成的 `flow2api-windows-package.zip` 可以传到远端 Windows。

不要打包这些内容：

```text
.git/
.venv/
data/
tmp/
test_outputs/
*.log
logs.txt
test_*
```

`data/flow.db` 里可能包含 Token、后台配置、窗口绑定等敏感信息。第一版建议不带数据库，让远端首次启动自动创建新数据库，再通过后台重新添加或导入 Token。

如果你明确要迁移本地已有 Token，可以单独复制 `data/flow.db`，但远端 BitBrowser 窗口 ID 可能变化，复制后仍要逐个检查 Token 的 `BitBrowser 窗口 ID`。

## 远端解压和安装

假设远端解压到：

```text
C:\flow2api
```

打开 PowerShell：

```powershell
cd C:\flow2api
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

如果远端只有 Python 3.11，也可以用：

```powershell
py -3.11 -m venv .venv
```

`bitbrowser` 模式一般不需要执行 `playwright install`。只有切到 `browser` 或 `personal` 打码模式时，才需要额外安装 Playwright 浏览器。

## 配置 Flow2API

编辑：

```text
C:\flow2api\config\setting.toml
```

最简远端配置建议：

```toml
[server]
host = "0.0.0.0"
port = 8000

[cache]
enabled = true
timeout = 86400
base_url = "http://<SERVER_PUBLIC_IP>:8000"

[captcha]
captcha_method = "bitbrowser"
bit_browser_base_url = "http://127.0.0.1:54345"
bit_browser_id = ""
bit_browser_close_on_shutdown = false
```

把 `<SERVER_PUBLIC_IP>` 替换成远端 Windows 的公网 IP。

如果只在远端电脑本机测试，可以先用：

```toml
base_url = "http://127.0.0.1:8000"
```

如果 `config/setting.toml` 不存在，先复制示例：

```powershell
Copy-Item config\setting_example.toml config\setting.toml
```

## 启动

确保 BitBrowser 已经启动，并且本地 API 地址可用：

```text
http://127.0.0.1:54345
```

启动 Flow2API：

```powershell
cd C:\flow2api
.\.venv\Scripts\Activate.ps1
python main.py
```

访问后台：

```text
http://<SERVER_PUBLIC_IP>:8000
```

默认后台账号：

```text
admin / admin
```

首次登录后立刻修改后台密码和 API Key。

## 后台配置顺序

1. 登录管理后台。
2. 修改管理员密码。
3. 修改 API Key。
4. 验证码方式选择 `bitbrowser`。
5. 确认 BitBrowser 本地 API 是 `http://127.0.0.1:54345`。
6. 添加 Flow Token。
7. 给每个 Token 填远端实际的 `BitBrowser 窗口 ID`。
8. 点击测试 Token，确认图片和视频都能生成。

## 验证

远端本机验证：

```powershell
curl.exe http://127.0.0.1:8000/models -H "x-goog-api-key: <FLOW2API_KEY>"
```

本地电脑访问远端验证：

```powershell
curl.exe http://<SERVER_PUBLIC_IP>:8000/models -H "x-goog-api-key: <FLOW2API_KEY>"
```

生成视频后，确认返回的 `fileData.fileUri` 类似：

```text
http://<SERVER_PUBLIC_IP>:8000/tmp/xxx.mp4
```

并且本地电脑可以直接打开或下载。

## 常见问题

### 解压后直接运行失败

通常是远端没有创建 `.venv` 或没有安装依赖。重新执行：

```powershell
cd C:\flow2api
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

### 打不开后台

检查：

- `setting.toml` 里 `host` 是否为 `0.0.0.0`。
- Windows 防火墙是否放行 `8000`。
- 云服务器安全组是否放行 `8000`。
- 服务是否仍在运行。

### BitBrowser 连接失败

检查：

- BitBrowser 客户端是否已经启动。
- 远端是否能打开 `http://127.0.0.1:54345`。
- Flow2API 的 `bit_browser_base_url` 是否是 `http://127.0.0.1:54345`。
- Token 里填写的是远端窗口 ID，不是本地窗口 ID。

### 生成成功但别人下载不了视频

检查：

- `[cache] enabled = true`。
- `base_url` 是否写成公网可访问地址。
- 防火墙和安全组是否允许访问 `8000`。
- 返回的 `fileUri` 是否是 `http://<SERVER_PUBLIC_IP>:8000/tmp/...`。

如果后续给外部用户长期使用，建议再补域名和 HTTPS；第一版自己远端测试可以先用公网 IP。
