# HTTP-01：Python 状态短语与 OpenAPI 可移植性

2026-10-03；范围仅为 router 错误描述。实现与定向 RED/GREEN 已完成；没有运行完整
release，也没有声称 Python 3.11、3.12、3.13 均已实测。

## 原因与最小修复

实际安装版本：Python 3.13.5、FastAPI 0.128.2、Starlette 0.50.0、Pydantic 2.13.4、
HTTPX 0.28.1、pytest 9.0.2。直接检查已安装源码：

- FastAPI `fastapi/openapi/utils.py` 410–417 行在显式响应没有 description 时，
  读取 `http.client.responses[status_code]` 作为 OpenAPI 描述。
- 本机 Python `http/client.py` 108 行从 `HTTPStatus` 成员的 phrase 构造此表；
  本机 422 短语为 `Unprocessable Content`。
- 两个 router 原有 ErrorResponse 条目均没有 description。把框架实际使用的 422
  短语改为 `Unprocessable Entity` 后，canonical exporter 的 `--check` 确实失败。
  这会阻断要求合同一致的默认启动，即使 DTO 和业务行为没有变化。

仅在 `routes.py` 和 `media_routes.py` 的既有错误响应条目中加入稳定描述：
400 Bad Request、404 Not Found、409 Conflict、422 Unprocessable Content、媒体 503
Service Unavailable。保留全部 ErrorResponse model、原状态码和原顺序。
不增加通用框架、不修改 exporter、不更改 Effect、schema owner 或 HTTP 处理逻辑。

执行 `.venv313/bin/python tools/export_contracts.py` 重新生成合同。OpenAPI JSON 的
对象属性顺序因 description 现在显式声明而改变，但解析后的 JSON 与修复前完全相同；
generated TypeScript 及 schemas.py 字节不变。`scope-proof.json` 保存前后 SHA-256，
并确认从修改后的 router AST 去掉新增 description 后，与修改前 AST 完全相同。

## 真实 RED → GREEN

同一测试文件 SHA-256：
`0f99cd4152ae2b1e6364e56e9e1c1d2a231dbc977387d726d3a8b4cb68f0a74d`。

运行顺序与结果：

1. `runs/001-red-20261003t1138z/`：6 项中 2 failed、4 passed，退出 1。
   原因是 Entity 变体导致 exporter drift，以及继承平台错误短语导致描述断言失败；
   不是 collection、依赖或测试语法错误。
2. 添加 router descriptions，并执行 canonical exporter。
3. `runs/002-green-20261003t1139z/`：完全相同的 6 项全部通过，退出 0。

测试每次建立新 app，不依赖缓存；直接 monkeypatch FastAPI 使用的
`http.client.responses`。两种 422 名称都执行真正 exporter `main --check`；
其他既有错误状态也使用替代短语验证显式描述、ErrorResponse schema 引用。
主路由、路径参数、媒体请求三种 422 实际 ASGI 响应仍符合 ErrorResponse，且不回显无效输入。

定向收据通过原 `record_check` 保存；调用时只替换 `git_head` 为返回 None，
避免执行本切片范围外的 Git 命令。记录中的 git_head=null；没有捏造 Git 检查。
每次 source_before/source_after 都是真实完整源码 hash 集合，changed_during_run 均为空。

## 消费者与独立失败

- `003-consumers-20261003t1139z/`：architecture 7 passed；specs 成功验证 90 个 requirement
  的可收集链接；HTTP 70 passed、1 failed。整体状态如实保留 failed。
- 失败为既有 `test_microphone_disconnect_during_final_drain_cancels_provider` 在关闭 WebSocket
  后等待 `stt.closed.wait(1)` 返回 False，见该运行 `http/stdout.txt`。没有改等待时长、
  测试或媒体行为来消除失败。
- `runs/005-drain-recheck-20261003t1140z/`：原失败 node 原样单独重跑，1 passed，0.34 秒。
- `006-consumers-recheck-20261003t1140z/`：同样 `architecture http specs --jobs 2` 原样重跑，
  architecture 7 passed、HTTP 71 passed、specs 90 个链接验证成功。
- 003 与 006 的 source_before_digest/source_after_digest 全部相同：
  `0dc79907d0478d6893ccffca53ede58a873f5d92cab62ec112549278faac06c3`。
  两次 changed_during_run 均为空；不能把后一次通过描述为已修复该间歇性取消失败。
  已交给集成负责人独立分析，media_routes.py 写权限于 11:42 UTC 释放。
- `runs/004-contract-and-startup-20261003t1139z/`：新合同测试、现有启动测试和 spec-link
  单元测试，共 30 passed；这是额外定向检查，不与上述重复测试相加计算样本量。
- `runs/007-final-export-check-20261003t1141z/`：canonical exporter `--check` 通过，
  changed_during_run 为空。

测试唯一 owner 由现有 `providers` 的 `tests/contracts/test_*.py` glob 覆盖。
没有修改 tests/quality.toml。11:41 的补充全目录 inventory 检查曾遇正在并行新增的
`tests/unit/test_jev_evaluator.py` 尚未落盘；这不是本切片修改。11:43 该文件已存在，
新测试的单一 providers 归属再次确认。最终集成检查由集成负责人执行。

## 验证边界

主质量命令为 `.venv313/bin/python tools/check.py --lane architecture http specs --jobs 2`；
仅选择三个 lane。domain、env、config、actor、完整 providers/tooling、web、package、smoke
未在这两个 lane 运行中执行；其中明确列出的定向测试另有收据。
没有执行 affected/full/release、远端 CI、真实浏览器、设备、外部服务或 live 端点；
没有读私密 `.env`、凭据、认证文件或 Git 元数据，没有安装依赖。

`.venv` 无法导入 FastAPI，所以未用它伪造第二 Python 环境实测。
`.venv313/bin/python -m ruff check tests/contracts/test_portable_openapi.py` 返回
`No module named ruff`，lint 未运行成功，也未为此安装工具。
跨版本保障来自对已安装框架真实平台短语入口的负控，不等同完整 Python 版本矩阵。

源码 hash 与消费者结果对应这里标明的执行时点；释放 ownership 后其他工作包的更改
必须由集成负责人重新验证，不把本记录冒充后续源码的全量绿灯。
