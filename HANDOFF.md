# HANDOFF

> 给 Codex/Work 的工单。新阶段整页覆盖写。执行 Agent 只读本文件 + SPEC.md。

## 当前状态
- 仓库 / 分支：https://github.com/wyxaivv1018-collab/IncidentPilot （默认分支）
- 基于 checkpoint：docs 初始化提交
- `git status` 是否干净：是（以远程为准；你本地若还没有 clone，先 clone 再开干）

## 本阶段目标（一个）
把仓库收成「可交给 coding agent 的最小起点」：确认三份文档齐全；本地 clone；准备下一阶段（最小可运行 Strands agent 骨架）的 HANDOFF。

**注意：本阶段不要大写业务代码。** 先接上仓库与文档。

## 已锁定（勿重新讨论）
- 私有仓：wyxaivv1018-collab/IncidentPilot
- 工作流文件：STATUS.md / SPEC.md / HANDOFF.md
- 产品方向见 SPEC.md
- 比赛向：Agents for Humans（Strands）；须在提交窗口内新建交付，不能原样交旧仓

## 禁止事项
- 不要删除或清空 SPEC/STATUS/HANDOFF
- 不要在本阶段引入复杂多 Agent / 上生产
- 不要在证据不足时实现「自动给最终结论」的逻辑
- 不要自己验收自己（另开审核窗）

## 要做的任务（小步）
1. [ ] `git clone https://github.com/wyxaivv1018-collab/IncidentPilot.git`（若本地还没有）
2. [ ] 打开 STATUS.md / SPEC.md / HANDOFF.md，确认能读到
3. [ ] 用户填写/确认 SPEC 里仍空或需改的验收条目
4. [ ] 下一阶段再开新的 HANDOFF：最小 Strands agent 可运行骨架（另写，勿在本阶段偷偷做大）

## 验收标准（PASS/FAIL）
- [ ] 远程仓库能打开三份 md
- [ ] 本地 clone 成功且三文件存在
- [ ] STATUS「下一步」仍清晰（未失控扩 scope）
- 测试命令：无（文档阶段）
- Demo 步骤：浏览器打开仓库 → 点开三个文件

## 交付物
- 代码改动：无（本阶段）
- 文档改动：STATUS.md 在你 clone 确认后更新「已做成」
- commit message 建议：`docs: confirm local clone and workflow files`

## 给审核窗的材料（阶段结束后填）
- 改了什么：
- 测试结果：
- 对照 SPEC 哪几条：
