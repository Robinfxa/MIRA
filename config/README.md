# 配置约定

## 位置与优先级

从低到高：`Settings` 类型默认 → `config/defaults.toml` → `config/profiles/<profile>.toml`
→ **显式选定**的根 `.env` → 进程环境 → 测试 overrides。

`python -m mira` / `scripts/dev` 显式选择仓库根 `.env`（存在才读取）；
`create_app(settings)` 和测试不会自动搜索当前目录或父目录 `.env`。
`config/loader.py` 是生产代码唯一读取环境变量的地方；模块 import 不读取配置、不连接网络。

## 分类

| 内容 | 放哪里 | 不放哪里 |
|---|---|---|
| 可公开的默认运行值 | defaults.toml | 业务模块常量、HTTP handler |
| 环境差分 | profiles/mock.toml、test.toml | 多份复制的完整配置 |
| 私密值 | 根 .env 或进程 MIRA_* | TOML、前端、版本库、日志 |
| 浏览器公开配置 | apps/web/src/shared/config.ts | 后端 Settings 的整体序列化 |
| 原创角色／动作资源 | 后续 content/ 版本化内容包 | 秘密环境变量或服务配置 |

前缀为 `MIRA_`，嵌套分隔符为 `__`。未知 MIRA_*、未知字段、非法 profile、越界参数均启动失败。
环境值先映射后经 Pydantic 校验；允许源数组使用 JSON。dotenv 禁止插值，不写入 `os.environ`。
秘密类型为 `SecretStr`，校验错误只返回字段路径，不包含原始值；TOML 中禁止 `api_key`。

当前可执行组合为 `generation=mock|replay + review=fixture`。
`profiles/replay.toml`只写差分。`MIRA_PROVIDERS__REPLAY_SCENARIO`仅允许photo-tour、delayed-photo、failed-tail；不是文件路径，不读取用户提供的JSON。回放只复用固定已审候选，不当作实际模型。
若根.env已有generation=mock，单改MIRA_PROFILE不能覆盖这个更高优先级字段；同时设MIRA_PROVIDERS__GENERATION=replay。
`codex/api/jev` 是配置词表里的未来接入槽，工厂会明确报未实现，绝不偷偷换成 Mock。
`allow_external_calls` 与 `allow_paid_api` 默认 false；当前版本设为 true 也会失败。

当前只绑定 loopback，单进程单 worker。多用户公网部署、跨进程状态和远端认证不在本切片内。
修改端口时同步 `allowed_origins`，测试优先用显式 Settings，而不是反复修改真实 .env。


## ENV-01：开发服务登记（foundation 0.4.0）

`Settings.services`由同一个loader读取，`config/profiles/development.toml`只写可公开差分；
`.env.development.example`是空模板，用`python tools/api_env.py init`显式创建私密文件。
这不是第二套业务配置、也不是已注册live adapter。现有factory依旧只允许mock/replay＋fixture。

- 明确映射SDK常用别名 `OPENAI_API_KEY`、`TYPESAFE_API_KEY`、`GOOGLE_CLOUD_PROJECT`、`GOOGLE_CLOUD_QUOTA_PROJECT`。
- 别名在每个来源层内归一，同层与MIRA字段冲突时报错；再按既有优先级覆盖。
- 不自动读取 `OPENAI_BASE_URL`，不提取Codex OAuth，不读取ADC文件，不修改进程环境。
- 新服务秘密不进入repr／model_dump，TOML递归拒绝api_key/access_token/refresh_token/private_key。
- `MIRA_PROVIDERS__API_KEY`为旧保留字段，不自动给任何新服务复用；新代码使用具名服务配置。
- `services.probe`仅授权开发工具的目录GET；与运行时外传／付费授权不同。不得将目录探测通过当作模型调用准入。

完整字段、API准备及剩余人工步骤见[开发API环境](../docs/development/API_ENV.md)。
