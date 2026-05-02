# Flow2API 稳定上游接入建议

本文档给 qiyuan-api 或其他上游服务接入 Flow2API 时使用，目标是用尽量稳定、结构化、可维护的方式调用图片和视频生成能力。

## 推荐接入方式

优先使用 Gemini 结构化接口：

```http
GET /models
POST /models/{model}:generateContent
POST /models/{model}:streamGenerateContent?alt=sse
```

鉴权支持以下三种方式：

```http
x-goog-api-key: <FLOW2API_KEY>
Authorization: Bearer <FLOW2API_KEY>
?key=<FLOW2API_KEY>
```

如果上游按 Gemini 协议适配，建议统一使用 `x-goog-api-key` 和 `/models` / `/models/{model}:generateContent`。`/v1/models` 和 `/v1/chat/completions` 也可用，但它们是 OpenAI 风格，更适合兼容 OpenAI SDK 的场景。

## 模型列表

```http
GET /models
x-goog-api-key: <FLOW2API_KEY>
```

返回 Gemini 风格模型列表，包含可用于 `generateContent` 的模型名和别名。

## 文生视频 T2V

```http
POST /models/veo_3_1_t2v_fast:generateContent
x-goog-api-key: <FLOW2API_KEY>
Content-Type: application/json
```

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

成功响应会返回 `fileData.fileUri`：

```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          {
            "fileData": {
              "mimeType": "video/mp4",
              "fileUri": "https://api.example.com/tmp/xxx.mp4"
            }
          }
        ]
      },
      "finishReason": "STOP",
      "index": 0
    }
  ],
  "modelVersion": "veo_3_1_t2v_fast_landscape"
}
```

## 图生视频 I2V

```http
POST /models/veo_3_1_i2v_s_fast_fl:generateContent
x-goog-api-key: <FLOW2API_KEY>
Content-Type: application/json
```

推荐使用 `inlineData` 传 base64 图片：

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "让画面中的人物自然转身看向镜头，背景保持稳定，电影感运镜"
        },
        {
          "inlineData": {
            "mimeType": "image/jpeg",
            "data": "<BASE64_START_IMAGE>"
          }
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

也支持 `fileData.fileUri`：

```json
{
  "fileData": {
    "mimeType": "image/jpeg",
    "fileUri": "https://example.com/input.jpg"
  }
}
```

注意：`fileData.fileUri` 必须是 Flow2API 服务器能直接下载到的图片 URL。为了减少外部网络和鉴权问题，上游能传 base64 时优先传 `inlineData`。

I2V 模型通常支持 1-2 张图片：1 张作为首帧，2 张作为首尾帧。具体图片数量限制以模型列表和服务返回错误为准。

## 多参考图视频 R2V

```http
POST /models/veo_3_1_r2v_fast:generateContent
x-goog-api-key: <FLOW2API_KEY>
Content-Type: application/json
```

R2V 支持 0-3 张参考图。图片同样建议优先使用 `inlineData`，其次使用 `fileData.fileUri`。

## 参数说明

`generationConfig.responseModalities: ["VIDEO"]` 当前不是强制字段，Flow2API 会根据模型名判断生成类型。但建议上游保留该字段，保持 Gemini 协议语义清晰。

`generationConfig.imageConfig.aspectRatio` 支持常见 Gemini 比例：

- `"16:9"`：横屏
- `"9:16"`：竖屏
- 其他比例是否有效取决于具体模型

视频别名会根据 `aspectRatio` 解析到具体内部模型。例如：

- `veo_3_1_t2v_fast` + `"16:9"` -> `veo_3_1_t2v_fast_landscape`
- `veo_3_1_t2v_fast` + `"9:16"` -> `veo_3_1_t2v_fast_portrait`

## 结果下载建议

生产环境建议开启 Flow2API 本地缓存，并配置公网可访问的 `cache_base_url`。这里的公网地址可以是正式域名，也可以是第一版验证用的公网 IP + 端口；关键是最终客户必须能访问 `fileData.fileUri`。

推荐效果：

```json
{
  "fileData": {
    "mimeType": "video/mp4",
    "fileUri": "https://api.example.com/tmp/xxx.mp4"
  }
}
```

这样上游只需要提取 `candidates[0].content.parts[].fileData.fileUri`，再按自己的业务包装成下载地址或 OpenAI-compatible 响应。

不建议长期直接暴露上游 `fifeUrl` 给最终客户，因为它可能受过期时间、代理、地区和下载头影响。Flow2API 缓存后的 `/tmp/xxx.mp4` 更适合作为对外下载源。

当前 `/tmp` 是 FastAPI 静态目录，访问不需要 API key。若视频下载量较大，建议生产环境用 Nginx 直接托管 `tmp` 目录，以获得更稳定的 Range 下载、Content-Type 和大文件传输能力。

有域名时的缓存配置建议：

```toml
[cache]
enabled = true
timeout = 0
base_url = "https://api.example.com"
```

暂时不买域名时，也可以用公网 IP + 独立下载端口：

```toml
[cache]
enabled = true
timeout = 86400
base_url = "http://<SERVER_PUBLIC_IP>:8080"
```

反向代理只开放媒体路径：

```text
http://<SERVER_PUBLIC_IP>:8080/tmp/* -> http://127.0.0.1:8000/tmp/*
```

`timeout = 0` 表示不自动清理缓存文件。若需要节省磁盘，可以设置为业务允许的有效期，例如 `86400` 秒。公网 IP 方案能跑通下载，但没有 HTTPS；如果客户在 HTTPS 网页里播放 HTTP 媒体，浏览器或上游平台可能拦截。正式对外服务建议补域名和 HTTPS，下载量变大后再考虑 OSS/CDN 或 qiyuan-api 媒体转存。

## 非流式与流式

第一版上游可以先使用非流式：

```http
POST /models/{model}:generateContent
```

非流式调用会在 Flow2API 内部提交视频任务并轮询上游，直到拿到最终视频 URL 后再返回。这个方式接入简单，但 HTTP 请求会长时间保持连接。

当前普通视频轮询主要受以下配置影响：

```toml
[flow]
poll_interval = 3.0
max_poll_attempts = 200
```

默认约等于 600 秒。若上游、网关或反向代理不允许长连接，非流式视频可能超时。

流式接口：

```http
POST /models/{model}:streamGenerateContent?alt=sse
```

流式接口会通过 SSE 返回进度事件，最终事件里也会返回 `fileData.fileUri`。它可以缓解网关空闲超时，但仍然不是可恢复的任务查询接口。

## 更稳的长期方案

如果 qiyuan-api 要正式对外提供视频生成服务，建议后续在 Flow2API 或 qiyuan-api 层增加异步任务接口：

```http
POST /v1/media/generations
GET /v1/media/generations/{task_id}
```

推荐流程：

1. 上游提交生成请求，立即返回 `task_id`。
2. Flow2API 后台生成和缓存媒体文件。
3. qiyuan-api 轮询任务状态或接收 webhook。
4. 任务成功后返回最终 `fileUri`。

这样可以避免单次 HTTP 请求挂 10 分钟以上，也方便做重试、断线恢复、排队、限流和用户侧进度展示。

## 稳定性注意事项

接口支持某个模型，不等于当前账号一定有该模型权限。实际部署时建议只暴露已验证可用的模型，或在上游做降级策略，例如 fast 模型不可用时降级到 lite 模型。

图片 URL 输入依赖 Flow2API 服务器能访问该 URL。若图片在内网、有鉴权、或需要特殊请求头，建议由 qiyuan-api 下载后转成 `inlineData` 传给 Flow2API。

对外下载地址建议始终使用 Flow2API 缓存后的公网 `/tmp` 链接，而不是上游原始链接。生产环境要确保 `cache_base_url` 是外部可访问域名，并且反向代理允许大文件下载。
