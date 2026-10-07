# 订阅生图：一次有界的本机组件检查

`tools/check_subscription_image.py` 只检查这条组件路线：固定的公开虚构空灯塔海岸
brief → 请求一张 1024×1024 PNG → 对实际规范化 PNG 的一次独立像素审核。
订阅返回仅接受 1024×1024、1536×1024、1024×1536，审核绑定实际宽高和像素；
不会把横图或竖图改写为方图。
使用生产 `StoryImageRuntime`、现有工厂与共享单任务准入。它不启动网页或服务，
不展示或保存图片，不改变剧情状态，也不会自动嵌入 bootstrap、测试或服务器。

## 默认不读取认证、不联网

从当前完整源码根目录、使用项目已安装依赖的 Python 执行：

```sh
python tools/check_subscription_image.py
```

`--check` 是同义的显式写法。退出 0 仅表示本地参数检查完成；
`configuration_only_unverified` 不验证账户、token、模型资格、订阅额度或真实路由。
默认不会创建凭据源、读取 `.env`、MIRA/Codex 登录文件、刷新 token 或发 HTTP。

## 真实执行须由操作者另外明确选择

下面命令会向 OpenAI 的内部订阅兼容接口发送固定虚构 brief 和生成的 PNG，
并可能消耗订阅额度；实际额度消耗未知，不能由本地次数限制推算费用或计划上限。
`REVIEW_MODEL` 必须替换为操作者明确选择的独立视觉审核模型名称，配置值不证明可用。

```sh
python tools/check_subscription_image.py --run \
  --review-model REVIEW_MODEL \
  --authorize-fiction-data-to-openai \
  --authorize-subscription-usage
```

缺少任一确认或审核模型会退出 2，认证与 HTTP 都不会开始。不会自动切换到 API，
不需要 API key、Codex CLI 或额外环境文件；没有自定义 prompt、图片、URL 或重试选项。
生成固定为 `gpt-image-2`、`n=1`、`quality=auto`。审核内容来自实际解码后的 PNG，
不是根据原始 brief 自行认定画面合格。生成失败、非法 PNG 或尺寸错误时不会审核。
审核未知、拒绝、不完整或绑定错误均不算通过。

默认复用 MIRA 自己的既有 OAuth 存储路径。仅已有登录放在不同绝对路径时，才加：

```sh
--auth-store /absolute/path/to/existing-mira-session.json
```

该选项不创建登录、授权 grant 或复制其他应用凭据。既有 MIRA 凭据源可能为已过期
token 执行它原有的刷新；这仍由已有认证流程管理，不增加新的持久权限。
不将认证文件或 token 粘贴到聊天、命令参数或报告中。

## 结果与固定边界

只输出一个 JSON 摘要：阶段、封闭类别码/细分码、结果状态、路线/模型名、本地任务与调用
计数、HTTP 状态数字或 null。不会输出异常原文、路径、响应内容、headers、认证、
prompt、base64、图片或审核描述。`image_http_requests` 与 `review_http_requests`
分别最多 1，表示各自 HTTP transport 的请求尝试；不是所有 HTTP 的总量。
既有 OAuth 刷新可能另外请求认证服务。没有收到 HTTP 响应时状态为 null。
`detail_code` 只允许枚举出的生产错误码，如 `image_json_invalid`、
`image_png_dimensions` 或 `subscription_review_observation_binding`；未知异常为
`unknown`，成功或没有组件异常时为 null。HTTP 200 本身不表示解析或审核成功。
`*_http_responses` 表示已收到响应头，不意味着响应体有效或服务商工作已完成。

`admitted_jobs` 与 `generation_attempts` 在第一次 provider await 前计入。
`review_attempts` 仅在图片通过生产解码后、调用审核前计入。失败、超时、取消不会
退还本次计数或自动重试，也不能保证服务商已停止处理已发出的请求。

继承上限：整个任务 120 秒、生成 90 秒、审核 45 秒；图片最多 8 MiB、生成 wire
最多 12,000,000 字节、审核 wire 最多 65,536 字节；一个任务占用现有共享准入。
审核本地文本上限 8192 字节，不宣称内部订阅接口提供远端 token 或费用硬限额。

| 退出码 | 含义 |
| --- | --- |
| 0 | 默认本地检查，或 `component_passed` 的实际组件成功 |
| 1 | 已开始的组件失败、超时或清理失败 |
| 2 | 参数、确认或配置不可用 |
| 130 | 已取消 |

`component_passed` 只证明这次生成与独立像素审核通过代码边界；不等于完整场景、
用户实际看图、剧情呈现回执、稳定账户资格或长期服务质量已经验收。
本切片只执行合成离线测试；真实执行仍需操作者另行选择上述命令。
