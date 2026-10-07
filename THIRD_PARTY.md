# 第三方与素材说明

## 本次实际运行依赖

FastAPI、Starlette、Pydantic、python-dotenv、Uvicorn、HTTPX、Google Cloud Speech / google-auth 及其锁定依赖、PyJWT 2.15.1 与 cryptography；PyJWT 只供可选本机登录辅助程序使用。PyJWT 的精确官方 wheel 哈希、上游来源和版本化 MIT 许可见 [`PyJWT 2.15.1 provenance`](docs/development/third-party-notices/pyjwt-2.15.1-provenance.md)。测试使用pytest、pytest-asyncio、pytest-cov；构建工具也单独锁定；
前端锁定 TypeScript 5.8.3、PixiJS 8.19.0 与 esbuild 0.28.2，版本和MIT许可证见 `package-lock.json`。PixiJS作为本地浏览器bundle的一部分；esbuild只用于构建。运行时不请求CDN。发布bundle保留esbuild生成的链接许可文本与第三方声明。
源码通过包导入，没有复制其底层实现。发布前按所分发具体包保留许可证及NOTICE。

Uvicorn 的可选 WebSocket 实现固定为 `wsproto==1.3.2`；纯 Python 包由 Uvicorn 自动选择，运行时不再依赖可选的 `websockets` 包。官方 PyPI wheel SHA-256、兼容性依据与本地真实 TCP 验证记录见 `docs/development/third-party-notices/wsproto-1.3.2-provenance.md`。wheel 的完整 MIT 许可文本保存在 `docs/development/third-party-notices/licenses/python/wsproto/1.3.2/LICENSE`。

PixiJS浏览器bundle的完整许可文本随包发布：可从应用获取 `/assets/licenses/THIRD_PARTY_NOTICES.txt`，构建产物中亦保留在 `/dist/licenses/`。该索引列出锁定的PixiJS 8.19.0和所有声明的运行时传递依赖，并附其完整许可文件；TypeScript类型包与构建工具不属于浏览器运行时bundle。esbuild生成的逐chunk `.LEGAL.txt` 也随dist保留。

## 原生工具与参考边界

Codex 原生客户端作为外部进程接入候选实现，当前版本/二进制/协议配置需要显式固定和准入。Google Cloud CLI 只用于单独授权的配置准备。仓库不分发这两个工具的二进制或认证材料，也没有复制完整 SIWC devkit。安装工具不代表允许任何账户或付费请求。

Codex／CLIProxyAPI／Pi、Pipecat／LiveKit、Charivo、Hindsight等：来源证据和许可边界保留在v0.6 A5。
除上述明确记录的原生工具外，不能把参考列表当实际运行依赖或账户授权表。

## 工作台素材

原创成年 MIRA 角色、雨夜咖啡馆与旅行插画包括为本项目编写的 SVG/CSS 和AI辅助生成的透明PNG全帧插画，不是第三方照片或既有人物肖像。使用系统字体，不分发字体包、第三方角色模型、第三方音频或用户图片。PNG状态帧与归属见 `apps/web/public/scene/ORIGINAL-ASSETS.md`；其哈希、真实尺寸与单一状态映射见本地 `mira_manifest.json`。素材及动画代码存在不等于真实浏览器/设备验收，也不代表实时模型生图。

## 许可范围

本交付没有代用户选择项目总体开源许可证；源架构和用户内容不因代码生成被重新授权。
真实依赖的公开文档与入口见 `docs/implementation/official-references.md`。
