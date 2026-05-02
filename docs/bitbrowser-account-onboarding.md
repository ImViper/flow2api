# BitBrowser 上号标准流程

这份文档给后续 AI 操作用。用户只需要完成网页登录和二次验证；窗口选择、代理配置、Token 绑定、验证和交接由 AI 按本文档执行。

## 触发条件

当用户说以下任意意思时，直接按本流程操作：

- `我要上号`
- `新增账号`
- `再上一批号`
- `打开比特让我登录`
- `把这个账号绑到窗口`

除非用户特别指定窗口或代理，否则 AI 自行选择空闲 BitBrowser 窗口和可用代理。

## 标准目标

每个 Google/Flow 账号固定绑定一组环境：

- 一个 BitBrowser 窗口
- 一个稳定代理出口
- 一个 Flow2API Token 记录
- 一个 `bit_browser_id`

不要多个账号共用一个 BitBrowser 窗口。不要在登录后随意更换该窗口代理。

## 安全规则

- 不保存、不询问、不打印 Google 密码。
- 不把 Session Token、Access Token、代理账号密码、API Key 写进 docs 或提交到 git。
- 可以在本机临时读取代理表格和配置，但输出时必须打码。
- 不提交代理 Excel、数据库、日志、`.env`、虚拟环境目录。
- BitBrowser 本地 API 只允许本机访问，不要暴露到公网。

## 前置检查

开始前先检查：

1. BitBrowser 客户端已启动，本地 API 可访问，默认是 `http://127.0.0.1:54345`。
2. Flow2API 已启动，例如 `http://127.0.0.1:8000`。
3. 验证码方式是 `bitbrowser`。
4. `personal_max_resident_tabs` 已设置合理上限，避免长期运行时 tab 增长。
5. 如果要联调 qiyuan-api，再确认 qiyuan-api 指向当前 Flow2API 地址。

如果启动日志出现全局 `BitBrowser 浏览器窗口 ID 未配置`，不一定是故障。只要后续 Token 记录里填写了自己的 `bit_browser_id`，请求会优先使用 Token 级窗口绑定。

## 窗口选择

优先选择满足这些条件的窗口：

- 最近不用或明确空闲。
- 没有登录其他 Google/Flow 账号。
- 没有异常风控状态。
- 代理地区符合用户目标，例如香港、新加坡、日本、美国等。

窗口命名建议：

```text
flow-YYYYMMDD-NN-region-purpose
```

示例：

```text
flow-20260430-01-hk-main
flow-20260430-02-sg-video
```

记录窗口 ID 时只记录 BitBrowser 的真实 `id`，不要把代理密码写进备注。

## 代理配置

如果用户提供了代理文件或代理信息，AI 可以自行挑选未使用代理配置到窗口里。

配置原则：

- 登录、reCAPTCHA、Flow 生成都使用同一个窗口代理。
- 代理失败时换窗口或换代理后重新登录，不要沿用旧登录状态硬切代理。
- 代理信息在输出和文档中只写地区、用途、最后四位或内部编号。

代理连通性至少检查：

- `https://accounts.google.com/`
- `https://labs.google/`
- `https://gemini.google.com/` 或 Flow 实际页面

## 打开窗口并让用户登录

AI 操作：

1. 打开选定 BitBrowser 窗口。
2. 在窗口中打开 `https://labs.google/fx/tools/flow`。
3. 如果未登录，让用户登录。
4. 等用户回复 `登录了`、`好了`、`继续` 之类确认。

用户只负责：

- 输入账号密码。
- 完成二次验证。
- 接受 Google/Flow 首次使用条款。

AI 不要要求用户提供密码或验证码内容。

仓库里提供了标准上号脚本，优先使用脚本执行打开窗口和后续绑定：

```powershell
python scripts\onboard_bitbrowser_account.py `
  --browser-id "<BITBROWSER_WINDOW_ID>" `
  --remark "flow-YYYYMMDD-NN-region-purpose" `
  --open-login
```

执行后让用户在打开的 BitBrowser 窗口中登录。用户回复登录完成后，再执行绑定：

```powershell
python scripts\onboard_bitbrowser_account.py `
  --browser-id "<BITBROWSER_WINDOW_ID>" `
  --remark "flow-YYYYMMDD-NN-region-purpose" `
  --bind
```

脚本输出只包含脱敏邮箱、Token ID、窗口 ID、余额和能力开关，不会打印 ST、AT、完整 cookie 或代理密码。

## 获取凭证

用户登录完成后，AI 通过 BitBrowser 的 CDP 连接该窗口，检查 Flow 页面是否已登录。

需要提取的主要凭证：

- `__Secure-next-auth.session-token`

如果没有该 cookie：

1. 刷新 Flow 页面。
2. 确认用户已进入 Flow 工具页。
3. 如有地区、条款、年龄或订阅弹窗，让用户在窗口中处理。
4. 再次读取 cookie。

不要把完整 cookie 输出到聊天或文档。

## 绑定到 Flow2API

新增 Token 时使用以下字段：

```json
{
  "st": "<SESSION_TOKEN>",
  "project_id": null,
  "project_name": null,
  "remark": "flow-20260430-01-hk-main",
  "captcha_proxy_url": null,
  "bit_browser_id": "<BITBROWSER_WINDOW_ID>",
  "image_enabled": true,
  "video_enabled": true,
  "image_concurrency": -1,
  "video_concurrency": -1
}
```

如果检测到同一账号或同一 Session Token 已存在，不要重复新增。应更新已有 Token：

- 替换新的 `st`
- 绑定正确的 `bit_browser_id`
- 更新备注
- 保持图片、视频能力按用户需求开启

Flow2API 会用 ST 转 AT，并创建或维护项目池。Token 级 `bit_browser_id` 优先级高于全局 `bit_browser_id`。

## 验证流程

绑定后按顺序验证：

1. 刷新 Token AT，确认没有 401。
2. 刷新余额，确认账号可访问 Flow。
3. 拉取模型列表，确认服务正常响应。
4. 发一次低成本图片生成请求。
5. 如该账号用于视频，再发一次短视频请求并下载返回的 `fileUri`。
6. 观察 BitBrowser 窗口不会无限新开 tab。

验证通过后交接给用户：

```text
已完成：
- 窗口：flow-20260430-01-hk-main
- BitBrowser ID：<masked-or-id>
- Token：#12 / user***@gmail.com
- 能力：图片=true，视频=true
- 代理：HK-***
- 验证：图片成功，视频成功，下载成功
```

不要输出 ST、AT、完整代理、完整 API Key。

## 常用本机检查命令

Flow2API 健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/ -UseBasicParsing
```

查看文档和代码中是否已有绑定说明：

```powershell
rg -n "bit_browser_id|BitBrowser|captcha_method" docs src config
```

打开 BitBrowser 窗口的 API 形态通常是：

```powershell
$base = "http://127.0.0.1:54345"
$body = @{ id = "<BITBROWSER_WINDOW_ID>" } | ConvertTo-Json
Invoke-RestMethod -Uri "$base/browser/open" -Method Post -Body $body -ContentType "application/json"
```

实际返回里通常会包含 CDP 调试地址，AI 应使用返回的调试地址连接浏览器上下文，再读取 cookie 或控制页面。

## 故障处理

`PUBLIC_ERROR_UNUSUAL_ACTIVITY`：

- 降低账号并发。
- 确认登录和生成都走同一代理。
- 暂停该账号一段时间。
- 必要时换干净代理并重新登录。

无法获取 Session Token：

- 让用户确认已经进入 Flow 工具页。
- 刷新页面并等待登录态稳定。
- 检查是否有条款、订阅、地区限制页面。

ST 转 AT 失败：

- 不要删除窗口。
- 重新读取 cookie。
- 如果 cookie 仍失败，让用户在该窗口重新登录。

窗口 tab 过多：

- 检查 `personal_max_resident_tabs` 和 `personal_idle_tab_ttl_seconds`。
- 重启 Flow2API 后会清理旧的 reCAPTCHA 孤儿页。
- 不要手动关闭用户正在登录或生成中的页面。

代理失败：

- 先停用该 Token。
- 换代理后重新登录。
- 更新窗口备注和 Token 备注，避免之后误用。

## 操作完成后的记录

每次上号结束，AI 需要给用户一份简短结果：

- 新增或更新了哪个账号。
- 使用哪个 BitBrowser 窗口。
- 图片、视频是否验证成功。
- 是否已下载验证产物。
- 是否有待处理风险，例如代理不稳、视频暂时未测、余额不足。

记录中只允许出现脱敏信息。
