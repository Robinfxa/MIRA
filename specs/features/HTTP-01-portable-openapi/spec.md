# HTTP-01 Python 版本间稳定的 OpenAPI 错误描述

范围：只在两个 HTTP router 的既有 ErrorResponse 声明中固定描述；不改变状态码、
响应 DTO、运行时处理、Effect 字段、FastAPI 或通用导出器。生成文件只由
`tools/export_contracts.py` 更新，不手改。

共同基点：沿用集成基点 `ebb578dde665c9c7269e4a64b508182680b2fa66`，本切片不执行 Git。
测试 owner：providers，现有 `tests/contracts/test_*.py` glob 唯一覆盖新测试。
消费者：architecture 的合同检查、http、默认离线启动前的 exporter check。
资源：已安装 `.venv313/bin/python`、合成 ASGI 请求、内存 OpenAPI；不安装第二环境，
不读取私密 `.env` 或凭据，不调用 live provider、不监听网络端口。
集成 owner 负责最终 affected/full/release；本切片做定向 RED/GREEN 和消费者检查。

### HTTP01-001 平台状态短语不产生合同漂移
Given 支持的 Python 版本把 HTTP 422 分别命名为 Unprocessable Entity 或
Unprocessable Content，When 固定依赖的 FastAPI 生成 OpenAPI 并执行 canonical
exporter 的 `--check`，Then 两种平台短语都通过同一份合同检查。
422 的项目描述明确固定为 Unprocessable Content，保留当前 Python 3.13 导出文字。
测试直接替换已安装 FastAPI 实际使用的 `http.client.responses[422]`，每次创建新 app，
避免已缓存 OpenAPI 掩盖差异；此模拟不等于在所有支持的 Python 版本实测。

### HTTP01-002 ErrorResponse 文档保持准确
Given 两个 router 现有的 400、404、409、422 和媒体 503 错误声明，When 平台默认短语变化，
Then 每个声明保留明确的项目描述与 `#/components/schemas/ErrorResponse` 引用。
Given 主路由或媒体路由的请求校验失败，When 发送合成无效请求，Then 实际 422 JSON
继续符合 ErrorResponse，包含 invalid_request、固定安全消息和关联 request_id，
不退回 FastAPI 默认 HTTPValidationError 或回显无效请求体。

运行证据：`docs/verification/http-01-portable-openapi/`。
未选范围明确为 not_run；本切片不代表完整产品、真机、远端 CI 或跨 Python 实测通过。
