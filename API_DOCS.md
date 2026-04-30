# Flow2API 对外接口文档

## 基础信息

- Base URL: `http://<host>:8000`
- Content-Type: `application/json`
- OpenAI 兼容接口认证: `Authorization: Bearer <API_KEY>`
- Gemini 兼容接口认证:
  - `x-goog-api-key: <API_KEY>`
  - `Authorization: Bearer <API_KEY>`
  - `?key=<API_KEY>`

## 模型列表

OpenAI 兼容格式:

```http
GET /v1/models
Authorization: Bearer <API_KEY>
```

Gemini 兼容格式:

```http
GET /models
x-goog-api-key: <API_KEY>
```

获取单个 Gemini 模型:

```http
GET /models/{model}
x-goog-api-key: <API_KEY>
```

### 支持模型

建议外部调用优先使用「别名模型」，由服务根据 `generationConfig.imageConfig.aspectRatio` 和 `generationConfig.imageConfig.imageSize` 自动解析到内部模型。也可以直接传内部完整模型名。

#### 图片模型别名

| 模型 | 能力 | 支持画幅 | 支持清晰度 |
| --- | --- | --- | --- |
| `gemini-3.1-flash-image` | 文生图、图生图 | `16:9`、`9:16`、`1:1`、`4:3`、`3:4` | 默认 / `1K`、`2K`、`4K` |
| `gemini-3.0-pro-image` | 文生图、图生图 | `16:9`、`9:16`、`1:1`、`4:3`、`3:4` | 默认 / `1K`、`2K`、`4K` |
| `gemini-2.5-flash-image` | 文生图、图生图 | `16:9`、`9:16` | 默认 / `1K` |
| `imagen-4.0-generate-preview` | 文生图、图生图 | `16:9`、`9:16` | 默认 / `1K` |

#### 图片内部完整模型名

- `gemini-3.1-flash-image`
- `gemini-3.0-pro-image`
- `gemini-2.5-flash-image`
- `imagen-4.0-generate-preview`
- `gemini-2.5-flash-image-landscape`
- `gemini-2.5-flash-image-portrait`
- `gemini-3.0-pro-image-landscape`
- `gemini-3.0-pro-image-portrait`
- `gemini-3.0-pro-image-square`
- `gemini-3.0-pro-image-four-three`
- `gemini-3.0-pro-image-three-four`
- `gemini-3.0-pro-image-landscape-2k`
- `gemini-3.0-pro-image-portrait-2k`
- `gemini-3.0-pro-image-square-2k`
- `gemini-3.0-pro-image-four-three-2k`
- `gemini-3.0-pro-image-three-four-2k`
- `gemini-3.0-pro-image-landscape-4k`
- `gemini-3.0-pro-image-portrait-4k`
- `gemini-3.0-pro-image-square-4k`
- `gemini-3.0-pro-image-four-three-4k`
- `gemini-3.0-pro-image-three-four-4k`
- `imagen-4.0-generate-preview-landscape`
- `imagen-4.0-generate-preview-portrait`
- `gemini-3.1-flash-image-landscape`
- `gemini-3.1-flash-image-portrait`
- `gemini-3.1-flash-image-square`
- `gemini-3.1-flash-image-four-three`
- `gemini-3.1-flash-image-three-four`
- `gemini-3.1-flash-image-landscape-2k`
- `gemini-3.1-flash-image-portrait-2k`
- `gemini-3.1-flash-image-square-2k`
- `gemini-3.1-flash-image-four-three-2k`
- `gemini-3.1-flash-image-three-four-2k`
- `gemini-3.1-flash-image-landscape-4k`
- `gemini-3.1-flash-image-portrait-4k`
- `gemini-3.1-flash-image-square-4k`
- `gemini-3.1-flash-image-four-three-4k`
- `gemini-3.1-flash-image-three-four-4k`

#### 视频模型别名

支持视频生成。视频模型分三类:

- T2V: text to video，文生视频，不接收图片。
- I2V: image to video，图生视频，接收 1 到 2 张图片；部分 lite/interpolation 模型有更严格图片数量。
- R2V: reference images to video，多参考图视频，最多 3 张参考图。

| 模型 | 类型 | 图片输入 | 说明 |
| --- | --- | --- | --- |
| `veo_3_1_t2v_fast` | T2V | 不支持 | 快速文生视频 |
| `veo_3_1_t2v_fast_ultra` | T2V | 不支持 | ultra 文生视频 |
| `veo_3_1_t2v_fast_ultra_relaxed` | T2V | 不支持 | ultra relaxed 文生视频 |
| `veo_3_1_t2v` | T2V | 不支持 | 标准文生视频 |
| `veo_3_1_t2v_lite` | T2V | 不支持 | lite 文生视频 |
| `veo_3_1_i2v_s_fast_fl` | I2V | 1-2 张 | 首帧/首尾帧视频 |
| `veo_3_1_i2v_s_fast_ultra_fl` | I2V | 1-2 张 | ultra 首帧/首尾帧视频 |
| `veo_3_1_i2v_s_fast_ultra_relaxed` | I2V | 1-2 张 | ultra relaxed 首帧/首尾帧视频 |
| `veo_3_1_i2v_s` | I2V | 1-2 张 | 标准首帧/首尾帧视频 |
| `veo_3_1_i2v_lite` | I2V | 1 张 | lite 首帧视频 |
| `veo_3_1_interpolation_lite` | I2V | 2 张 | lite 首尾帧插帧视频 |
| `veo_3_1_r2v_fast` | R2V | 0-3 张 | 多参考图视频 |
| `veo_3_1_r2v_fast_ultra` | R2V | 0-3 张 | ultra 多参考图视频 |
| `veo_3_1_r2v_fast_ultra_relaxed` | R2V | 0-3 张 | ultra relaxed 多参考图视频 |

视频别名同样支持通过 `generationConfig.imageConfig.aspectRatio` 选择横竖屏:

- `16:9` / `landscape`: 横屏，默认值。
- `9:16` / `portrait`: 竖屏。

#### 视频内部完整模型名

- `veo_3_1_t2v_fast_portrait`
- `veo_3_1_t2v_fast_landscape`
- `veo_3_1_t2v_fast_portrait_ultra`
- `veo_3_1_t2v_fast_ultra`
- `veo_3_1_t2v_fast_portrait_ultra_relaxed`
- `veo_3_1_t2v_fast_ultra_relaxed`
- `veo_3_1_t2v_portrait`
- `veo_3_1_t2v_landscape`
- `veo_3_1_t2v_lite_portrait`
- `veo_3_1_t2v_lite_landscape`
- `veo_3_1_i2v_s_fast_portrait_fl`
- `veo_3_1_i2v_s_fast_fl`
- `veo_3_1_i2v_s_fast_portrait_ultra_fl`
- `veo_3_1_i2v_s_fast_ultra_fl`
- `veo_3_1_i2v_s_fast_portrait_ultra_relaxed`
- `veo_3_1_i2v_s_fast_ultra_relaxed`
- `veo_3_1_i2v_s_portrait`
- `veo_3_1_i2v_s_landscape`
- `veo_3_1_i2v_lite_portrait`
- `veo_3_1_i2v_lite_landscape`
- `veo_3_1_interpolation_lite_portrait`
- `veo_3_1_interpolation_lite_landscape`
- `veo_3_1_r2v_fast_portrait`
- `veo_3_1_r2v_fast`
- `veo_3_1_r2v_fast_portrait_ultra`
- `veo_3_1_r2v_fast_ultra`
- `veo_3_1_r2v_fast_portrait_ultra_relaxed`
- `veo_3_1_r2v_fast_ultra_relaxed`
- `veo_3_1_t2v_fast_portrait_4k`
- `veo_3_1_t2v_fast_4k`
- `veo_3_1_t2v_fast_portrait_ultra_4k`
- `veo_3_1_t2v_fast_ultra_4k`
- `veo_3_1_t2v_fast_portrait_1080p`
- `veo_3_1_t2v_fast_1080p`
- `veo_3_1_t2v_fast_portrait_ultra_1080p`
- `veo_3_1_t2v_fast_ultra_1080p`
- `veo_3_1_i2v_s_fast_portrait_ultra_fl_4k`
- `veo_3_1_i2v_s_fast_ultra_fl_4k`
- `veo_3_1_i2v_s_fast_portrait_ultra_fl_1080p`
- `veo_3_1_i2v_s_fast_ultra_fl_1080p`
- `veo_3_1_r2v_fast_portrait_ultra_4k`
- `veo_3_1_r2v_fast_ultra_4k`
- `veo_3_1_r2v_fast_portrait_ultra_1080p`
- `veo_3_1_r2v_fast_ultra_1080p`

支持画幅:

- `16:9`
- `9:16`
- `1:1`
- `4:3`
- `3:4`

支持清晰度:

- 默认 / `1K`
- `2K`
- `4K`

说明:

- `gemini-2.5-flash-image` 主要支持横屏、竖屏。
- `imagen-4.0-generate-preview` 主要支持横屏、竖屏。
- `gemini-3.0-pro-image` 和 `gemini-3.1-flash-image` 支持更多画幅和 `2K` / `4K`。
- 使用别名模型时，服务会根据 `generationConfig.imageConfig.aspectRatio` 和 `generationConfig.imageConfig.imageSize` 自动解析到内部模型。
- 视频生成需要 token 开启 `video_enabled`，并受 token 的 `video_concurrency`、账号层级和上游额度限制。

## OpenAI 兼容接口

### 文生图

```bash
curl -X POST "$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3.1-flash-image",
    "messages": [
      {
        "role": "user",
        "content": "一张棚拍产品照：黑色陶瓷咖啡杯，极简灰色背景，柔和灯光"
      }
    ],
    "generationConfig": {
      "imageConfig": {
        "aspectRatio": "1:1",
        "imageSize": "1K"
      }
    },
    "stream": false
  }'
```

### 图生图

```bash
curl -X POST "$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3.1-flash-image",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "把这张图改成水彩插画风格，保留主体构图"
          },
          {
            "type": "image_url",
            "image_url": {
              "url": "data:image/jpeg;base64,<BASE64_IMAGE>"
            }
          }
        ]
      }
    ],
    "generationConfig": {
      "imageConfig": {
        "aspectRatio": "1:1",
        "imageSize": "1K"
      }
    },
    "stream": false
  }'
```

`image_url.url` 支持:

- `data:image/jpeg;base64,...`
- `data:image/png;base64,...`
- `http(s)://...`
- 服务本地缓存 `/tmp/...` URL

### 流式调用

```bash
curl -N -X POST "$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3.1-flash-image",
    "messages": [
      {
        "role": "user",
        "content": "雨夜霓虹街道，湿润路面反光，电影感广角，真实摄影风格"
      }
    ],
    "stream": true
  }'
```

返回类型: `text/event-stream`

### 文生视频

```bash
curl -X POST "$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "veo_3_1_t2v_fast",
    "messages": [
      {
        "role": "user",
        "content": "一段 8 秒电影感视频：雨夜城市街道，霓虹灯反射在湿润路面，缓慢推进镜头"
      }
    ],
    "generationConfig": {
      "imageConfig": {
        "aspectRatio": "16:9"
      }
    },
    "stream": false
  }'
```

OpenAI 兼容响应里，`choices[0].message.content` 会返回 HTML 视频标签:

```html
<video src='http://<host>:8000/tmp/<video>.mp4' controls></video>
```

### 图生视频

```bash
curl -X POST "$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "veo_3_1_i2v_s_fast_fl",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "让画面中的人物自然转身看向镜头，背景保持稳定，电影感运镜"
          },
          {
            "type": "image_url",
            "image_url": {
              "url": "data:image/jpeg;base64,<BASE64_START_IMAGE>"
            }
          }
        ]
      }
    ],
    "generationConfig": {
      "imageConfig": {
        "aspectRatio": "16:9"
      }
    },
    "stream": false
  }'
```

I2V 模型传 1 张图片时作为首帧，传 2 张图片时作为首尾帧。`veo_3_1_interpolation_lite` 必须传 2 张图片。

## Gemini 兼容接口

### 文生图

```bash
curl -X POST "$BASE_URL/models/gemini-3.1-flash-image:generateContent" \
  -H "x-goog-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "systemInstruction": {
      "parts": [
        {
          "text": "Return exactly one image. Do not include explanatory text."
        }
      ]
    },
    "contents": [
      {
        "role": "user",
        "parts": [
          {
            "text": "雨夜霓虹街道，湿润路面反光，电影感广角，真实摄影风格"
          }
        ]
      }
    ],
    "generationConfig": {
      "responseModalities": ["IMAGE"],
      "imageConfig": {
        "aspectRatio": "16:9",
        "imageSize": "1K"
      }
    }
  }'
```

成功响应示例:

```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          {
            "inlineData": {
              "mimeType": "image/jpeg",
              "data": "<BASE64_IMAGE>"
            }
          }
        ]
      },
      "finishReason": "STOP",
      "index": 0
    }
  ],
  "modelVersion": "gemini-3.1-flash-image-landscape"
}
```

### 图生图

```bash
curl -X POST "$BASE_URL/models/gemini-3.1-flash-image:generateContent" \
  -H "x-goog-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [
          {
            "text": "将图片改成赛博朋克海报风格"
          },
          {
            "inlineData": {
              "mimeType": "image/jpeg",
              "data": "<BASE64_IMAGE>"
            }
          }
        ]
      }
    ],
    "generationConfig": {
      "responseModalities": ["IMAGE"],
      "imageConfig": {
        "aspectRatio": "9:16",
        "imageSize": "1K"
      }
    }
  }'
```

也支持 `fileData`:

```json
{
  "fileData": {
    "mimeType": "image/jpeg",
    "fileUri": "https://example.com/input.jpg"
  }
}
```

### 流式调用

```http
POST /models/{model}:streamGenerateContent
POST /v1beta/models/{model}:streamGenerateContent
```

可选参数:

```http
?alt=sse
```

返回类型: `text/event-stream`

### 文生视频

```bash
curl -X POST "$BASE_URL/models/veo_3_1_t2v_fast:generateContent" \
  -H "x-goog-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
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
  }'
```

成功响应示例:

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
              "fileUri": "http://<host>:8000/tmp/<video>.mp4"
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

### 图生视频

```bash
curl -X POST "$BASE_URL/models/veo_3_1_i2v_s_fast_fl:generateContent" \
  -H "x-goog-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [
          {
            "text": "让主体自然向前移动，镜头轻微跟随，保持写实风格"
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
        "aspectRatio": "9:16"
      }
    }
  }'
```

## 请求字段说明

### OpenAI 兼容字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 是 | 模型名或模型别名 |
| `messages` | array | 是 | OpenAI Chat Completions 消息数组 |
| `messages[].role` | string | 是 | `user` / `assistant` / `system` 等 |
| `messages[].content` | string 或 array | 是 | 文本或多模态内容 |
| `stream` | boolean | 否 | 是否流式返回，默认 `false` |
| `generationConfig` | object | 否 | Gemini 风格生成配置 |
| `generationConfig.imageConfig.aspectRatio` | string | 否 | 图片或视频画幅 |
| `generationConfig.imageConfig.imageSize` | string | 否 | 图片清晰度；视频模型忽略该字段 |

### Gemini 兼容字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `contents` | array | 是 | Gemini contents 数组 |
| `contents[].role` | string | 否 | `user` 或 `model` |
| `contents[].parts` | array | 是 | 内容片段 |
| `parts[].text` | string | 否 | 文本提示词 |
| `parts[].inlineData` | object | 否 | Base64 图片输入 |
| `parts[].fileData` | object | 否 | 图片 URL 输入 |
| `systemInstruction` | object | 否 | 系统提示词 |
| `generationConfig.responseModalities` | array | 否 | 图片传 `["IMAGE"]`，视频传 `["VIDEO"]` |
| `generationConfig.imageConfig.aspectRatio` | string | 否 | 图片或视频画幅 |
| `generationConfig.imageConfig.imageSize` | string | 否 | 图片清晰度；视频模型忽略该字段 |

## 错误响应

OpenAI 兼容接口错误示例:

```json
{
  "error": {
    "message": "错误原因",
    "type": "generation_error",
    "status_code": 400
  }
}
```

Gemini 兼容接口错误示例:

```json
{
  "error": {
    "code": 400,
    "message": "错误原因",
    "status": "INVALID_ARGUMENT"
  }
}
```

常见 HTTP 状态:

| 状态码 | 说明 |
| --- | --- |
| `400` | 请求参数错误，例如提示词为空、图片格式不支持 |
| `401` | API Key 无效或缺失 |
| `404` | 模型不存在 |
| `429` | 上游限流或 token 暂不可用 |
| `500` | 服务内部错误或上游异常 |

## 客户端超时建议

图片生成建议客户端 HTTP 超时至少设置为 `300s`。单张图片通常需要几十秒到数分钟，外部调用方不要使用很短的请求超时。

视频生成建议客户端 HTTP 超时至少设置为 `1500s`。带 `1080p` / `4k` 后缀的视频模型会在生成后继续执行视频放大，耗时可能接近 30 分钟。
