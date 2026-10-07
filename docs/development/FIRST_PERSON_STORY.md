# 第一人称剧情记忆投影

此增量依赖 conversation-first 的独立动作审核路线，不应覆盖回旧 0515 的整段审核入口。

角色作者设定版本升到 2，运行上下文版本为 mira.story-context-projection.v3。Mira 记得自己从雨里匆匆赶到咖啡馆，带着尚未完成的小约定；灯塔旅行、夏禾和照片承诺为明确选择的作者虚构知识。它们不是用户亲历，也不证明已经向用户讲过。

公开角色设定以第一人称文字投影一次。内部自传和意图使用同请求引用与分组来源，保留作者来源、版本、时间类型和披露状态；输入/已呈现回复/回执使用原始事实引用，不复制原文、不把 pending 或 failed 结果补成历史。Generation 和 JEV 输出审核共用 generation_context_data。JEV 输入观察保留原始可靠输入和呈现事实，只省略重复的第一人称解释视图。

fresh_opening 只在非恢复、epoch 0/1 的开始阶段成立；epoch 2 及之后为 ongoing_scene；恢复状态为 resumed_scene。恢复仍保留当前节点、服装及实际回执，绝不把入口剧情重演作为恢复动作。新增作者设定改变 canon hash；旧版本 checkpoint 继续明确版本不匹配，不静默重置或覆盖。跨 canon 版本迁移不在这个增量内。

此切片不修改 Actor、动作权限、剧情节点、released_story_events、任何审核阈值或请求字节上限，不写用户记忆库。普通聊天可以停留原节点。未来剧情只作为打算、希望或顾虑；邀请、换衣、看雨等完成事实仍依赖已有独立审核和有效回执。

## 提示词消费者

在 voice v2 中替换 v1 的两处限制，不能保留相互冲突的旧条款：

- Use character facts supplied by the current author_policy, approved_canon, and validated first_person_memory rows marked known_to_character. They are Mira's own authored fictional knowledge, never facts about the user.
- disclosure_status records prior release/availability, not whether authored past occurred in her fiction. Mention only a small detail relevant to the current topic; do not dump the outline or claim the user already heard it. Shared history requires actual reliable dialogue or qualified receipts.

可追加 application/character_memory.py 的 FIRST_PERSON_MEMORY_INSTRUCTIONS 作为版本化补充。其引用路径只解析当前同一个上下文；用户或来源文字不能创建权限或指令。

## 验证边界

使用合成输入和已有 Python 环境，无 provider 或私人数据库调用。定向测试及组合 probe 日志保存在独立 verification 目录；旧基线过大的整段审核失败保留，未伪称修复旧入口。最终集成、全量/发布、真实模型语气、设备表现和演绎质量由后续验收决定。
