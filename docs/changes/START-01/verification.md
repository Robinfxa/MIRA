# START-01 首次使用启动预设核验

核对日期：2026-10-07。此切片只增加启动包装器、公开模板字段、对应规格与测试；`tools/live_provider.py`、应用、provider backend 和原预算不变。它不替代冻结运行时的既有验收，也不构成新的全量 release 结果。

## 已实现的入口

`sh scripts/start` 首次明确选择真实订阅预设、离线排练或取消。真实预设使用原命令的 `gpt-6.1-sol`、Fast、Google 语音、临时剧情、生图和 `gpt-6-luna` 图片审核。选择保存于本目录 `var/launcher/choice.json`，绑定源码目录和本机身份；发布包排除 `var`。非交互且没有本机选择时不启动真实服务；`--accept-live-profile` 是明确接受该预设数据／用量范围的入口。

公开 `.env.example` 包含可编辑的 `MIRAAPP_*` 启动字段、Gacrux／`gemini-3.8-flash-tts`／global 和指定中文风格。包装器仅提取闭集启动字段；现有 loader 继续读取服务字段。CLI 明确值覆盖 `.env`。授权不接受 `.env` 声明，官方 API 仍要求原 CLI 的明确路线及计费同意。

缺失的默认 `.env` 以 0600 独占创建；已有文件的内容和权限不改，自选缺失文件不自动创建。Google project 须由使用者填写，MIRA 登录和 ADC 须在本机准备。HOME 路径与空格作为单个参数处理，不 source/eval 配置。预检只读取登录／ADC 的文件元数据，不读取其内容、刷新凭据或调用服务。

`--dry-run` 展示所选模式的参数，`--check` 做本地预检；两者不保存选择或启动服务。已保存离线选择时，两者也按离线处理。`--setup` 只调用原 `tools/bootstrap.py`，在项目 `.venv`／`node_modules` 使用既有锁文件，完成后退出。普通启动不会自动安装。

## 实际检查及收据

| 检查 | 结果 | 收据 |
|---|---|---|
| 定向 RED：缺启动默认行为／缺声音模板字段 | 2 条按预期失败；不是收集错误 | [001 RED](../../verification/start-preset-01/runs/001-red-20261007t0212z/report.json) |
| 新启动器与相邻原入口、配置、开发启动、质量规则、架构守卫 | 165 条通过，8.43 秒；源码前后无变化 | [002 GREEN](../../verification/start-preset-01/runs/002-green-20261007t0222z/report.json) |
| 最终规格映射 | 573 条 requirement 对应可收集节点；仅收集，不等于执行 | [003 规格](../../verification/start-preset-01/runs/003-final-spec-20261007t0223z/report.json) |
| 最终启动器合同 | 41 条通过，0.54 秒；源码前后无变化 | [004 最终](../../verification/start-preset-01/runs/004-final-launcher-20261007t0223z/report.json) |

41 条包含在相邻检查范围中，不与 165 累加计算。覆盖：空目录、既有配置保留、缺依赖／登录／ADC、文件权限与符号链接、带空格路径、HOME 三种写法、字面 shell 表达式、首次取消、无 TTY、保存选择的目录绑定、离线隔离、精确参数、配置／CLI 优先级、禁止配置授予许可或切官方 API、失败输出脱敏、安装与启动分离。所有配置／账号／ADC 测试均使用临时合成文件。

额外手动本地检查：原 `live_provider.py check` 使用公开模板加合成 project、不可解析的假 ADC 文本通过，未调用 provider。Python 编译检查通过。Ruff 未安装，本次未执行 Ruff，也未为此安装新依赖。

开发中补齐了真实预设字段的 `.env` 可配置性，修正预览／检查遵循已保存离线模式，并纠正模板末行对两种读取者的说明；最终 41 条测试在上述改动后重跑。

## 尚未验证

未执行全新机器联网安装计时、真实 OAuth／Google 登录或刷新、真实模型／语音／图片调用、Mac／手机／浏览器实机验收。文件存在、配置预检成功或 `--dry-run` 参数正确均不证明账户资格、额度、费用、实时质量或设备可用。此切片未重跑冻结核心的完整 release 套件。

文件清单：`tools/start_mira.py`、`scripts/start`、`.env.example`、`tests/contracts/test_start_mira_launcher.py`、`specs/features/START-PRESET-01/spec.md`、`specs/features/START-PRESET-01/traceability.json`、`tests/quality.toml` 的窄启动规则，以及本说明和上述追加收据。测试文件由既有 providers contract glob 唯一拥有。
