# MIRA 架构与开源复用整合书 v0.6

**日期：2026-10-03。** 合并架构书v0.5与开源实现借鉴书v0.1；保留已确认G01–G06，将现成实现具体接到模块、合同、工作包和验收。没有新增技术栈批准或产品运行结果。

## 阅读入口

- [整本HTML](MIRA_架构全书_v0.6.html)：桌面目录、手机章节导航、正文过滤搜索。
- [整本Markdown](MIRA_架构全书_v0.6.md)：自动汇编阅读版。
- [总设计书](docs/architecture/00-master-design-book.md)：领域合同与复用定位。
- [M10工作包](docs/architecture/modules/10-reuse-integration-and-work-packages.md)：WP01–WP08。
- [A4分歧](docs/architecture/appendices/A4-integration-differences-and-boundaries.md)：IC-01等显式差分。
- [A5源码索引](docs/architecture/appendices/A5-open-source-evidence-and-licenses.md)：16项目、固定commit和原阅读范围。
- [A6追踪](docs/architecture/appendices/A6-requirement-reuse-traceability.md)：需求→模块→复用→WP→RI。

只维护`docs/architecture/`及`docs/reference/`的当前源；历史目录不改。某项`recommended_not_integrated`不是已安装依赖。借鉴书原来的18项RI现在已显式并入总164项，全部not_run。

## 重建文档（不是启动MIRA产品）

```sh
python3 tools/build_book.py
python3 tools/build_html.py
python3 tools/check_book.py
```

HTML构建使用mistune；可选布局检查需本地已安装Playwright和Chromium：

```sh
python3 tools/check_layout.py
```

工具不发出外部请求、不安装依赖、不读取账户凭据。缺少本地渲染工具会明确报错；不自动下载浏览器。布局检查仅模拟文档视口，不验证MIRA设备体验。

## 历史与证据

v0.5原章节及导出在`docs/history/edition-v0.5/`；借鉴书v0.1原包在`docs/history/open-source-reference-v0.1/`。原始语音、需求和研究快照保持。`docs/reference/source-manifest.json`及`integration-provenance.json`记录来源和摘要；上游源码只保存索引而非声称完整离线镜像。

本次没有联网核查上游、安装产品依赖、运行上游或MIRA测试、登录模型、使用生图、变更GitHub。具体认证／承载分歧IC-01仍需选定配置上的准入，不因整合报告自动解决。
