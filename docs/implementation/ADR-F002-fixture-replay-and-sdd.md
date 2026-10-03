# ADR-F002：有限回放adapter与规格／测试示范

状态：本轮“打样骨架、开发记录、TDD/SDD”授权内的实施选择；不是新的产品G项，未独立人工评审。

新增replay作为原GenerationBackend的本地固定替身。3份随包资源只引用一个只读fixture catalog；不建立通用脚本执行器。配置集中、工厂显式、等待Callable注入。将fixture catalog从具体生成adapter提到同级共享所有者，避免review依赖某个生成器的实现模块。

SDD目录只定义可观察行为和测试索引；公共schema仍保留在HTTP DTO。记录工具只用于本地测试，输出不可覆盖；Git只在交付目录初始化，不push。已存在FND-01测试作为基线，不倒补成TDD历史。

HTTP schema/前端wire不变，FastAPI的API版本仍0.1.0；交付package版本是0.2.0，不混同消息协议版本。

证据：specs/features/FND-02-fixture-replay、docs/changes/FND-02、docs/verification/fnd-02。
局限：仅生成夹具回放；没有持久会话重放、真实语音、原创角色、生图或模型账户。
