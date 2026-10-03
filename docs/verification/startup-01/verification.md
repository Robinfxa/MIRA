# STARTUP-01：启动／安装包验证

2026-10-03；基点 `ebb578dde665c9c7269e4a64b508182680b2fa66`。仅本地云端工程，未提交、推送或发布。

## 可以直接使用的命令

已有依赖时：

```sh
sh scripts/dev
# 多解释器／未激活环境：
sh scripts/dev --python /absolute/path/to/ready/python
# 本次实际工程环境的命令：
sh scripts/dev --python .venv313/bin/python
# 固定回放：
sh scripts/dev --python .venv313/bin/python --profile replay --replay-scenario photo-tour
```

浏览器手动打开 `http://127.0.0.1:8000`；自选端口加 `--port 8123`。源码不硬编码 `.venv313`，这里只记录实际已安装依赖的环境名称。
不完整的默认 `.venv` 不再遮住可用的当前解释器；显式 `--python` 失败不会静默换一个。导入探针最多 15 秒，Node 版本检查最多 10 秒，合同／编译检查分别有 45／90 秒上限。服务持续运行直到停止。

默认命令不安装依赖，不读根 `.env`；loader 接收显式 mock/replay、fixture review、禁止外部及付费调用、禁止原文记录的参数。进程中的服务配置与常用凭据变量不会传入启动子进程。它是配置隔离，不是 OS 网络／文件系统沙箱。根 `.env` 与认证缓存没有被读取或修改。

显式依赖准备仍是 `python3 tools/bootstrap.py`。它需要注册表访问，安装项目环境，不属于“已有依赖后的离线一键演示”。`scripts/dev` 为 0644 的归档也可直接用 `sh` 调用。

## 改动

- `tools/dev.py`：实际解释器能力探针、显式选择、受限 mock/replay 参数、无自动安装、安全默认 settings、清晰缺依赖退出。
- `scripts/dev`／README：可移植归档调用说明；旧 `--no-bootstrap` 保留为无安装兼容选项。
- `pyproject.toml`：标准 setuptools data-files 保留 `config/`、`apps/web/` 布局，包含 HTML、CSS、worklet、原创 SVG／素材说明与全部当前编译模块。构建依赖固定为 setuptools 84.0.0、wheel 0.48.0；运行时依赖未由本切片修改。
- `setup.py`：最小标准 build_py 守卫。缺失入口 JS 或任何 TypeScript 对应 JS 时明确失败；不自动下载或执行 npm install。
- `tools/verify_package.py`：临时源码副本编译前端，无索引／无依赖／无构建隔离地构建 wheel，再安装到临时 `--target`。比较所有配置／静态文件 SHA-256，再在 `-I` 隔离解释器中确认 `mira` 导入与 `project_root()` 均来自安装目录。无 checkout PYTHONPATH 兜底。
- `tests/unit/test_dev_startup.py`、`test_package_distribution.py` 与 STARTUP-01 spec／traceability。测试块归属由集成 owner 登记为 tooling。

## 实际证据

每条收据和完整 stdout／stderr 都在 [runs/](runs/)，旧失败未覆盖。

| Run | 结果与范围 |
| --- | --- |
| 001-red-startup-package | 9 failed／3 passed：复现错误选择 `.venv`、自动安装、无隔离 demo、缺失 wheel config/static 等行为；源码无运行中变更 |
| 002-green-startup-package | 同一初始 12 项通过；源码无运行中变更 |
| 003-offline-installed-wheel | 实际安装资源校验失败，捕获新增 diagnostics/status.js 未声明进包。不是依赖或 collection 失败；没有记为通过 |
| 004-green-installed-wheel | 补齐声明后实际 wheel 构建／安装通过；system Python 3.12.14 构建，已批准 Python 3.13.5 运行烟测 |
| 005-documented-command-loopback | mock／replay 控制闭环实际通过，但运行期间 tools/quality_run.py 被集成 owner 修改；不可作为同一快照最终 GREEN |
| 006-expanded-tooling-regression | 扩充负控后 16 项通过；新增已通过负控属于回归 baseline，不倒补 RED |
| 007-ordinary-offline-installed-wheel | 集成 owner 准备锁定 build tools 后，普通不带 override 的 package 命令通过 |
| 008-documented-command-loopback | 重新运行两种真实 shell 启动：合同、TS 编译、loopback HTTP、静态资源、session、输入、许可、回执、停止、重传、删除均通过；合成 live `.env`／进程配置被忽略；源码无运行中变更 |
| 009-red-build-pin-enforcement | 实际负例：构建解释器未遵守 pyproject 的精确构建 pin，1 failed |
| 010-green-build-pin-enforcement | 同一测试通过，声明的精确 build requirements 必须匹配现成解释器 |
| 011-final-startup-tooling | 最终 17 项通过；源码无运行中变更 |
| 012-final-ordinary-wheel | 最终普通 package 命令通过；30 个配置／web 资源 SHA-256 一致，25 个 web 资源逐一 HTTP 200 且字节一致；3 个 replay fixture、health、session CRUD、私密路径 404；源码无运行中变更 |

最终 wheel 检查命令：

```sh
.venv313/bin/python tools/verify_package.py
```

实测版本：Python 3.13.5；Node 24.19.0；TypeScript 5.8.3；pip 26.2.1；setuptools 84.0.0；wheel 0.48.0。构建与运行依赖均为既有／集成 owner 显式安装的锁定环境。工具本身没有安装到这些解释器。

最终局部集成：`tools/check.py --lane tooling architecture specs --jobs 2` 通过，tooling 88 项、architecture 7 项，specs 79 条映射可收集；报告为 `var/quality/startup-01-final-tooling-integration-20261003T1112Z/summary.json`，源码无运行中变更。其余 domain/env/config/actor/providers/http/web/package/smoke 在该局部命令中明确 not_run；上表的独立 package／loopback 检查另有真实收据，不挪用为这些 lane 的结果。

最终 package wheel SHA-256（本次临时构建，未作为发布文件保存）：`a572b13aab983c26d0ec1fd88431818bc140b4ca0fa1bb32e38824616898e6c8`。没有承诺跨机器字节级可复现。

## 边界与后续

- 安装包烟测是临时 target＋已批准解释器依赖的 ASGI 检查；不是从零下载依赖的新机器部署，也未执行安装后的 `mira` console-script 真正 loopback 启动。
- shell loopback 测试运行临时源码副本，用显式合成 `.env` 与虚假的进程凭据作为负控；它没有读现有私密配置、调用真实 provider 或处理私人音频。
- 没有浏览器／手机、声音可听见、真实语音中断或 live provider 的验收结论；Windows、macOS 与全局／用户级安装未实测。原 164 条产品验收状态不改变。
- 新增前端目录需要补标准 data-files 声明；安装包完整资源校验会对漏项明确失败，不能静默绿灯。
- 全库 affected/full/release 与最终发布收口由集成 owner 基于最终冻结源码完成，本报告不替代它们。
