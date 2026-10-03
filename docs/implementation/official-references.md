# 本次实施核查来源

检索日期：2026-10-03。仅用于基础库使用方法，不替换用户原架构，也不证明目标账户能力。

- FastAPI lifespan： https://fastapi.tiangolo.com/advanced/events/ — 工厂与启动/退出资源边界。
- Pydantic Settings： https://docs.pydantic.dev/latest/concepts/pydantic_settings/ — 配置校验与环境来源概念；本实现采用Pydantic BaseModel＋显式loader，未引入额外Settings框架。
- Vite 环境安全： https://vite.dev/guide/env-and-mode — 核查浏览器配置不可承载secret；本切片未使用Vite，避免引入非必要运行依赖。
- uv projects： https://docs.astral.sh/uv/guides/projects/ — 核查环境隔离和可重复依赖；本切片采用venv＋精确requirements快照，不冒充生成了uv.lock。
- TypeScript： https://www.typescriptlang.org/tsconfig/strict.html — strict检查；本轮实际编译器5.8.3。

容器不能解析公开包注册表，未在本轮重新安装依赖；requirements是实际已安装版本闭包，
不是重新运行依赖解析器产生的wheel-hash锁。npm锁只固定一个TypeScript包，fresh npm ci尚未验证。

## FND-02 辅助核查（2026-10-03）

Python asyncio task cancellation: https://docs.python.org/3.13/library/asyncio-task.html
pytest monkeypatch与显式依赖: https://docs.pytest.org/en/stable/how-to/monkeypatch.html
setuptools package data: https://setuptools.pypa.io/en/latest/userguide/datafiles.html
仅用于核查测试/取消/资源包装语义，不升级本工程锁定依赖，不用文档替代实测。
