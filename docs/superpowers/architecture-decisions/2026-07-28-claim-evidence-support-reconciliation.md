# Claim 多来源证据与删除后支持状态重算

状态：已采用

日期：2026-07-28

## 背景

同一个画像 Claim 可以由多份简历支持。现有实现同时把 Evidence ID 保存在
`profile_claim_versions.evidence_ids_json` 和 `profile_claim_sources.source_ref_json`
中，但删除影响预检只读取前者。

因此，当第二份简历通过 `profile_claim_sources` 补充来源后，删除第一份简历仍可能
错误地把 Claim 标记为 `unsupported`。历史数据还可能保留指向已删除版本、状态却仍为
`active` 的来源记录。

此外，多份简历描述相近但不完全相同时，直接自动合并会扩大事实范围，例如“灰度发布”
不能未经确认就等同于“Nginx 灰度发布”。

## 决策

1. Claim 是稳定画像实体，当前内容版本和来源关系分别管理。
2. Claim 的直接依据由以下来源并集计算：
   - 当前 ClaimVersion 的兼容 Evidence ID；
   - 该 Claim 历史版本上所有 `active` Source 引用的 Evidence ID。
3. Evidence 只有同时满足以下条件才是有效直接依据：
   - 属于当前 Workspace；
   - Evidence 未 tombstone；
   - MaterialVersion 与 Material 均未删除。
4. 删除材料或单个版本时：
   - 将命中目标版本或 Evidence 的 Source 标记为 `source_deleted`；
   - 以剩余有效 Evidence 重新计算 Claim 支持状态；
   - 仍有直接依据时保持 `supported`，全部失效后才持久化为 `unsupported`。
5. “相似描述”不写入持久化的直接支持关系。统一画像投影按确定性关键词匹配展示
   `related`，并同时返回可核对的材料、版本、章节和短摘录。
6. 用户本人输入、画像助手对话或系统归纳且无简历 Evidence 时，统一画像投影为
   `manual`，不再与“来源已经失效”混为一类。
7. 使用一次性修复脚本清理历史脏状态并重算持久支持状态：

   ```bash
   uv run python scripts/repair_profile_claim_support.py \
     --database /path/to/runtime.sqlite \
     --workspace <workspace-id>
   ```

## 展示语义

- `supported`：存在有效直接原文依据；
- `related`：剩余材料中找到相关描述，需要人工决定是否关联；
- `manual`：本人或受控对话确认，不依赖简历原文；
- `conflicted`：不同来源存在事实冲突；
- `unsupported`：没有直接依据，也没有可供核对的相关内容。

`related` 和 `manual` 是统一画像的派生展示状态，不写入
`profile_claim_versions.support_status` 的数据库约束。下游读取不能把 `related`
视为已确认直接证据。

## 未采用方案

- 不把全部 Evidence ID 继续复制回每个 ClaimVersion JSON；这会让来源关系在版本更新后
  再次分叉。
- 不使用 LLM 或向量相似度自动合并 Claim；相关内容只提供核对入口。
- 不在前端根据黄色标签猜测来源状态；来源是否删除由后端事实决定。

## 影响

- 删除预检、执行、统一画像和下游 Context 读取使用同一套有效 Evidence 规则。
- 历史 Source 不再因 Claim 内容版本更新而不可见。
- 页面能解释“哪份材料的哪段文字仍然相关”，但最终是否把相关内容升级为直接依据仍需
  后续人工关联能力。
