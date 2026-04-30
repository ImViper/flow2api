# qiyuan-api 与 Flow2API 同服务器部署方案

本文档面向把 `qiyuan-api` 和 `flow2api` 部署在同一台服务器上的场景。当前 Flow2API 依赖 BitBrowser 窗口复用登录态和代理环境，因此推荐先用 Windows Server 部署。

## 结论

同机部署是可行的，推荐架构是：

```text
公网客户端
  -> qiyuan-api 公网域名
  -> qiyuan-api 内部调用 Flow2API
  -> Flow2API 调用本机 BitBrowser API / 已登录浏览器窗口
```

生产环境建议只把 qiyuan-api 对公网开放。Flow2API、BitBrowser 本地 API、数据库、Redis 都应绑定内网或本机地址，并通过防火墙阻断公网访问。

当前没有改 qiyuan-api 代码的前提下，要特别注意媒体文件地址：qiyuan-api 的原生 Gemini 路由会把 Flow2API 的响应基本原样返回，所以 `fileData.fileUri` 必须是客户端能访问的地址。也就是说，第一版要么公开 Flow2API 的 `/tmp` 静态文件路径，要么后续在 qiyuan-api 增加下载转存/代理逻辑。

## 推荐部署拓扑

```text
Windows Server

Nginx/Caddy/IIS 反向代理
  - https://api.example.com        -> http://127.0.0.1:3000  qiyuan-api
  - https://media.example.com/tmp/ -> http://127.0.0.1:8000/tmp/ Flow2API 静态缓存

qiyuan-api
  - 监听 127.0.0.1:3000 或 0.0.0.0:3000
  - 数据库使用 PostgreSQL/MySQL，低并发也可 SQLite
  - Redis 可选，生产建议启用
  - Gemini 类型渠道指向 Flow2API

Flow2API
  - 监听 127.0.0.1:8000
  - captcha_method = "bitbrowser"
  - cache.enabled = true
  - cache.base_url = "https://media.example.com"

BitBrowser
  - 本地 API: http://127.0.0.1:54345
  - 每个 Flow/Google 账号固定绑定一个 BitBrowser 窗口 ID
```

如果 qiyuan-api 用 Docker 跑，而 Flow2API 在 Windows 宿主机直接跑，qiyuan-api 渠道里的 Flow2API 地址不要写 `127.0.0.1:8000`，应写：

```text
http://host.docker.internal:8000
```

因为容器里的 `127.0.0.1` 指的是容器自身。

## 为什么推荐 Windows Server

当前这套模式的稳定性来自 BitBrowser：

- 每个窗口可以单独设置代理。
- 已登录 Google/Flow 的浏览器环境可以长期复用。
- Flow2API 可以通过 BitBrowser API 打开指定窗口，并通过 CDP 获取验证码/会话所需信息。

Linux 服务器单独部署时，BitBrowser 这条链路不能直接照搬。除非改成 Linux 可用的有头浏览器、远程桌面、打码服务或 remote browser 模式，否则现在依赖 BitBrowser 的账号维护方式会断掉。

所以第一版生产部署建议：

```text
Windows Server + BitBrowser + Flow2API + qiyuan-api
```

如果将来要 Linux 化，建议把浏览器能力独立成远程浏览器服务，再让 Flow2API 调用它。

## qiyuan-api 侧配置

qiyuan-api 当前默认端口是 `3000`，环境变量里支持：

```env
PORT=3000
SQL_DSN=postgresql://user:password@host:5432/new-api
REDIS_CONN_STRING=redis://:password@host:6379/0
SESSION_SECRET=<long-random-string>
RELAY_TIMEOUT=0
STREAMING_TIMEOUT=300
UPDATE_TASK=true
BATCH_UPDATE_ENABLED=true
```

生产环境不要沿用 `docker-compose.yml` 里的默认数据库和 Redis 密码。

qiyuan-api 管理后台里建议设置：

```text
ServerAddress = https://api.example.com
```

这个地址会影响 qiyuan-api 自己的视频代理地址，例如 `/v1/videos/{task_id}/content`。

## qiyuan-api 渠道配置

在 qiyuan-api 后台新增一个 Gemini 渠道：

```text
渠道类型: Gemini
Base URL: http://127.0.0.1:8000
Key: <FLOW2API_KEY>
Models:
  gemini-3.1-flash-image-landscape
  gemini-3.1-flash-image
  veo_3_1_t2v_lite_landscape
  veo_3_1_t2v_lite
  veo_3_1_i2v_s_fast_fl
  veo_3_1_r2v_fast
```

如果 qiyuan-api 跑在 Docker 容器里：

```text
Base URL: http://host.docker.internal:8000
```

`veo_3_1_t2v_fast` 当前账号不一定有权限。之前测试中 fast 模型返回过 `MODEL_ACCESS_DENIED`，而 lite 提交成功，所以第一版建议先开放已验证的 lite/可用别名，fast 模型等账号权限确认后再放开。

## 请求路径建议

qiyuan-api 支持原生 Gemini 路由：

```http
GET /v1beta/models
POST /v1beta/models/{model}:generateContent
POST /v1beta/models/{model}:streamGenerateContent?alt=sse
```

它会转发到 Flow2API：

```http
GET http://127.0.0.1:8000/v1beta/models
POST http://127.0.0.1:8000/v1beta/models/{model}:generateContent
```

第一版建议让 qiyuan-api 上游使用 Gemini 结构化请求，尤其是视频：

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "一段 8 秒电影感视频：雨夜城市街道，霓虹灯反射在湿润路面，缓慢推进镜头"
        }
      ]
    }
  ],
  "generationConfig": {
    "responseModalities": ["VIDEO"],
    "imageConfig": {
      "aspectRatio": "16:9"
    }
  }
}
```

Flow2API 返回：

```json
{
  "candidates": [
    {
      "content": {
        "parts": [
          {
            "fileData": {
              "mimeType": "video/mp4",
              "fileUri": "https://media.example.com/tmp/xxx.mp4"
            }
          }
        ]
      }
    }
  ]
}
```

## 媒体文件方案

### 第一版：Flow2API 暴露 `/tmp`

这是最少改动方案。

Flow2API 配置：

```toml
[cache]
enabled = true
timeout = 0
base_url = "https://media.example.com"
```

反向代理只开放静态文件路径：

```text
https://media.example.com/tmp/* -> http://127.0.0.1:8000/tmp/*
```

不要把 Flow2API 的管理接口和生成接口直接暴露到公网。可以在反向代理层只允许 `/tmp/`，其他路径全部拒绝。

这种方案下，qiyuan-api 返回给客户端的 `fileData.fileUri` 是 Flow2API 缓存后的公网 URL，客户端可直接下载。

### 第二版：qiyuan-api 转存/代理媒体

这是长期更干净的方案。

qiyuan-api 收到 Flow2API 返回后：

1. 提取 `candidates[].content.parts[].fileData.fileUri`。
2. 在服务器内网下载该文件。
3. 存到 qiyuan-api 自己的对象存储、本地静态目录或代理接口。
4. 返回 qiyuan-api 自己的下载地址给上游客户。

这样 Flow2API 可以完全不对公网开放，公网只暴露 qiyuan-api。

当前 qiyuan-api 的原生 Gemini handler 会原样转发响应，尚未做这一步。因此如果不改 qiyuan-api，第一版必须让 Flow2API 的 `fileUri` 可公网访问。

## 超时与轮询

视频生成是长任务。第一版非流式请求要保证链路上的超时足够长：

```text
客户端 -> qiyuan-api:       建议 900-1800 秒
qiyuan-api -> Flow2API:     RELAY_TIMEOUT=0 或至少 900-1800 秒
反向代理 proxy timeout:     900-1800 秒
Flow2API 内部视频轮询:       poll_interval * max_poll_attempts
```

Flow2API 当前默认：

```toml
poll_interval = 3.0
max_poll_attempts = 200
```

也就是普通视频轮询约 600 秒。1080p/4K 或高峰期可能不够，需要按实际模型耗时调大。

qiyuan-api 自身也支持 OpenAI 风格视频任务接口和后台任务轮询：

```http
POST /v1/videos
GET /v1/videos/{task_id}
GET /v1/videos/{task_id}/content
```

但这条链路针对的是 qiyuan-api 自己的 task adaptor，不等同于直接把 Gemini `generateContent` 响应改写成 qiyuan 下载地址。第一版建议先用 Gemini 非流式 `generateContent` 跑通；后续如果要更稳，再在 qiyuan-api 做专用媒体转存和任务轮询。

## Flow2API 侧配置

建议生产配置要点：

```toml
[server]
host = "127.0.0.1"
port = 8000

[api_keys]
enabled = true
keys = ["<FLOW2API_KEY>"]

[cache]
enabled = true
timeout = 0
base_url = "https://media.example.com"

[captcha]
captcha_method = "bitbrowser"
bit_browser_base_url = "http://127.0.0.1:54345"
bit_browser_id = ""
bit_browser_close_on_shutdown = false
```

每个 Token 建议单独绑定：

```text
BitBrowser 窗口 ID
代理
账号状态
可用模型权限
```

不要把真实 API key、代理密码、账号密码提交到 Git。

## 进程管理

Windows Server 上建议：

- BitBrowser 设置为开机自启，保持可用桌面会话。
- Flow2API 用 NSSM、WinSW 或任务计划程序托管为常驻进程。
- qiyuan-api 可以直接跑 Windows 可执行文件，也可以 Docker 跑。
- 数据库和 Redis 可 Docker 跑，但生产密码必须换掉。

如果 qiyuan-api 直接跑宿主机：

```text
qiyuan-api -> http://127.0.0.1:8000
```

如果 qiyuan-api 跑 Docker：

```text
qiyuan-api -> http://host.docker.internal:8000
```

## 安全边界

必须做到：

- Flow2API 生成接口不直接暴露公网。
- BitBrowser API `54345` 不暴露公网。
- 数据库、Redis 不暴露公网。
- qiyuan-api 的 `SESSION_SECRET` 必须设置成长随机值。
- Flow2API API key 只保存在 qiyuan-api 渠道配置或服务端环境里。
- 反向代理只把 `media.example.com/tmp/` 转到 Flow2API 静态缓存目录。
- 定期清理或限制 `tmp` 目录大小，避免视频缓存撑满磁盘。

## 验收步骤

1. 在服务器上启动 BitBrowser，并确认对应窗口已登录 Flow/Google。
2. 启动 Flow2API，确认本机可访问：

```powershell
curl.exe http://127.0.0.1:8000/models -H "x-goog-api-key: <FLOW2API_KEY>"
```

3. 启动 qiyuan-api，确认公网可访问：

```powershell
curl.exe https://api.example.com/v1beta/models -H "x-goog-api-key: <QIYUAN_TOKEN>"
```

4. 在 qiyuan-api 后台新增 Gemini 渠道，Base URL 指向 Flow2API。
5. 用 qiyuan-api 发一次图片生成请求，确认能返回图片。
6. 用 `veo_3_1_t2v_lite_landscape` 发一次视频请求，确认返回 `fileData.fileUri`。
7. 从外网下载 `fileUri`，确认：

```text
HTTP 200
Content-Type: video/mp4
大文件下载不中断
```

8. 再测试一次 I2V：分别测试 `inlineData` base64 图片和 `fileData.fileUri` 图片。

## 推荐落地顺序

1. 先在 Windows Server 上跑通 BitBrowser + Flow2API。
2. 开启 Flow2API 缓存，并配置 `cache.base_url` 到媒体域名。
3. 部署 qiyuan-api，创建 Gemini 渠道指向 Flow2API。
4. 先开放已验证模型，尤其是 `gemini-3.1-flash-image-landscape` 和 `veo_3_1_t2v_lite_landscape`。
5. 稳定后再开放 fast、4K、R2V、I2V 等更贵或更容易受账号权限影响的模型。
6. 第二阶段再做 qiyuan-api 媒体转存/代理和任务轮询，减少长连接和公开 Flow2API `/tmp` 的依赖。
