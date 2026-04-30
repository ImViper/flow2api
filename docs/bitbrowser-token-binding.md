# BitBrowser Token 级窗口绑定

本文档说明本项目当前的 BitBrowser 接入方式，以及如何让多个已配置代理的 BitBrowser 窗口分别服务不同 Flow 账号。

## 目标

BitBrowser 模式用于复用你已经打开并登录过 Google/Flow 的 BitBrowser 窗口，通过 CDP 连接该窗口获取 reCAPTCHA token 和刷新 Flow session token。

这次改造后，每个 Token 可以单独绑定一个 `bit_browser_id`。请求生成时会优先使用 Token 绑定的 BitBrowser 窗口；如果 Token 未绑定窗口，则回退到验证码配置里的全局 `bit_browser_id`。

## 配置项

验证码配置中仍然需要：

- `captcha_method = "bitbrowser"`
- `bit_browser_base_url`：BitBrowser 本地 API 地址，例如 `http://127.0.0.1:54345`
- `bit_browser_id`：可选的全局默认窗口 ID

Token 新增字段：

- `bit_browser_id`：当前 Token 专用的 BitBrowser 浏览器窗口 ID

优先级：

1. Token 的 `bit_browser_id`
2. 全局验证码配置的 `bit_browser_id`
3. 两者都为空时，运行时会报错提示未配置 BitBrowser 浏览器窗口 ID

## 管理页

Token 新增和编辑弹窗里都有 `BitBrowser 窗口 ID` 字段。

推荐做法：

1. 在 BitBrowser 中创建窗口，例如 `flow-1`、`flow-2`
2. 给每个窗口配置各自代理
3. 在对应窗口中登录 Google/Flow
4. 在管理页添加或编辑 Token，把该账号对应的窗口 ID 填到 `BitBrowser 窗口 ID`
5. 验证码方式选择 `bitbrowser`

## 导入导出

Token 导入 JSON 支持 `bit_browser_id` 字段：

```json
[
  {
    "session_token": "xxx",
    "email": "example@gmail.com",
    "bit_browser_id": "flow-1",
    "image_enabled": true,
    "video_enabled": true
  }
]
```

Token 导出也会带上 `bit_browser_id`，方便后续迁移或批量维护。

## 运行时流程

1. 生成请求命中某个 Token
2. `FlowClient` 根据 Token 读取 `bit_browser_id`
3. `BrowserCaptchaService.get_instance(..., bit_browser_id=...)` 获取该窗口对应的服务实例
4. 服务实例通过 BitBrowser API 打开或连接对应窗口
5. Playwright 通过 CDP 复用该窗口上下文
6. 常驻打码页按 `窗口 ID + project_id` 绑定，避免多个窗口之间串用
7. Flow API 请求会尽量复用该窗口采集到的浏览器指纹请求头

## 多窗口注意事项

- 每个账号尽量固定使用同一个 BitBrowser 窗口。
- 代理出口、Google 登录环境、Flow 请求环境要尽量一致。
- 不建议多个账号共用同一个窗口，除非你明确接受账号状态互相影响。
- 如果某个窗口换了代理，建议先在该窗口里确认 Google/Flow 可正常访问，再用项目发起生成。

## 常见问题

### `PUBLIC_ERROR_UNUSUAL_ACTIVITY: reCAPTCHA evaluation failed`

这类错误通常不是代码异常，而是 Google/Flow 风控认为本次 reCAPTCHA 或请求环境不可信。常见原因：

- 代理质量差或切换频繁
- Google 登录 IP 和生成请求 IP 差异过大
- 同一账号并发太高
- 新账号或低信誉账号触发额外风控
- BitBrowser 窗口未真正登录 Flow

建议先降低并发，用同一个窗口、同一个代理连续完成登录和生成测试。

### 保存 bitbrowser 配置时全局窗口 ID 可以为空吗

可以。现在支持 Token 级窗口绑定，全局 `bit_browser_id` 只是默认值。只要参与生成的 Token 配了自己的 `bit_browser_id`，全局窗口 ID 就不必填写。

### 项目会保存 Google 账号密码吗

不会。项目只保存 Flow session token 和 BitBrowser 窗口 ID，不需要保存 Google 账号密码。登录动作应在 BitBrowser 窗口里手动完成。
