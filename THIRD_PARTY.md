# 第三方与素材说明

## 本次实际运行依赖

FastAPI、Starlette、Pydantic、python-dotenv、Uvicorn、HTTPX、Google Cloud Speech / google-auth 及其锁定依赖、PyJWT 与 cryptography；测试使用pytest、pytest-asyncio、pytest-cov；构建工具也单独锁定；
前端只用TypeScript编译器，运行时无前端包；对应版本见requirements/*.lock与package-lock.json。
源码通过包导入，没有复制其底层实现。发布前按所分发具体包保留许可证及NOTICE。

## 原生工具与参考边界

Codex 原生客户端作为外部进程接入候选实现，当前版本/二进制/协议配置需要显式固定和准入。Google Cloud CLI 只用于单独授权的配置准备。仓库不分发这两个工具的二进制或认证材料，也没有复制完整 SIWC devkit。安装工具不代表允许任何账户或付费请求。

Codex／CLIProxyAPI／Pi、Pipecat／LiveKit、Charivo、Hindsight等：来源证据和许可边界保留在v0.6 A5。
除上述明确记录的原生工具外，不能把参考列表当实际运行依赖或账户授权表。

## 工作台素材

原创成年 MIRA 角色、雨夜咖啡馆、旅行插画和表情是为本项目编写的 SVG/CSS，不是第三方照片或既有人物肖像。使用系统字体，不分发字体包、第三方角色模型、第三方音频或用户图片。素材及动画代码存在不等于真实浏览器/设备验收，也不代表实时模型生图。

## 许可范围

本交付没有代用户选择项目总体开源许可证；源架构和用户内容不因代码生成被重新授权。
真实依赖的公开文档与入口见 `docs/implementation/official-references.md`。
