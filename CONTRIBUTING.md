# 团队协作规范（3 人 + 各自 AI 智能体）

> 本项目由 **3 人并行开发**，每人使用 AI 智能体（Copilot / Codex 等）辅助编码。
> 本文是**人类**的协作规则；**智能体**的规则见 `.github/copilot-instructions.md` 与
> `.github/instructions/role-*.instructions.md`（文件级领地守卫）。

**仓库**：https://github.com/chienchen-png/finance-agent-workbench
**待办清单**：`改进问题.md`（7 个问题）

---

## 0. 一句话原则

> **Git 不是「大家同时编辑云端同一份文件」，而是「每人一份完整副本，各自改完再合并」。**
>
> 合并是**逐行判断、把改动并起来**，不是「二选一」。
> 前提是：**改动的文件尽量不重叠**——这正是本文要规定「改动范围」的原因。

---

## 1. 账号与权限


| 方案                                | 说明                                                        | 建议          |
| :------------------------------------ | :------------------------------------------------------------ | :-------------- |
| **A** 各自 GitHub 账号 + 加作协作者 | 提交能追溯到人；可互相 review PR                            | ✅**推荐**    |
| **B** 三人共用你的账号              | 能正常 push/pull，但**无法区分谁提交**、无法互相 approve PR | ⚠️ 临时可行 |

**若只能用方案 B（共用账号）**，必须在每台电脑上设置**各自的提交身份**，
让 commit 作者可区分：

```bash
# 每个人在自己电脑上执行（名字/邮箱换成自己的）
git config user.name  "角色A"
git config user.email "roleA@finance.local"
```

> 已验证：`git log` 会显示各自的作者，能区分。但 GitHub 上的 PR / review 无法按人区分。

**加作协作者（方案 A）**：仓库 → `Settings` → `Collaborators` → `Add people`。

---

## 2. 分支模型

```
main  ●────────────────●───────────●───────────●   ← 永远可运行，受保护
       \              / \         / \         /
        feat/A-2    /   feat/B-3 /   feat/C-1 /
                    \          /             /
                     (PR + 自检后合并)
```


| 分支                          | 用途           | 规则                              |
| :------------------------------ | :--------------- | :---------------------------------- |
| `main`                        | 稳定主线       | **禁止直接 push**，只通过 PR 合并 |
| `feat/<角色>-<问题号>-<简述>` | 各自的工作分支 | 例：`feat/A-2-header-anchor`      |

**分支命名示例**

```
feat/A-2-header-detect-fix      角色A · 问题2 · 表头识别修复
feat/B-3-recon-report-quality   角色B · 问题3 · 核对报告质量
feat/C-1-model-config-linkage   角色C · 问题1 · 模型配置联动
```

**保护 main（仓库 -> Settings -> Branches -> Add rule）**

- ✅ Require a pull request before merging
- ✅ Require status checks（若有 CI）
- ❌ 不要勾选 "Require approvals"（3 人且可能共用账号时会卡死流程）

---

## 3. 分工矩阵（核心）

> 目标：**每个文件只有一个主人**。文件不重叠 → 零冲突。


| 角色     | 负责问题                              | 定位           | 独占领地（主要文件）                                                                                                                                                                                                                                                                                                                                                                               |
| :--------- | :-------------------------------------- | :--------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A**    | **2** 数据识别准确性**6** 部署上线    | 数据与基础设施 | `tools/table_layout_detector.py``tools/project_data_importer.py``tools/project_data_tools.py``tools/formula_fallback.py``tools/excel_tools.py``routes/project_data.py``app.py``config/**``requirements.txt``frontend/vite.config.ts``frontend/package.json``frontend/src/components/AppDataPanel.tsx``frontend/src/components/DataPanel.tsx``scripts/**`                                           |
| **B**    | **3** 数据核对报告**7** 报告问题      | 报告链路       | `routes/apps.py` 🔥`routes/files.py``routes/finmod_refs.py``tools/reconcile_tool.py``tools/finmod_*.py``tools/_finmod_models.py``tools/financial_analysis_tools.py``frontend/src/pages/DataCheckAppPage.tsx``frontend/src/pages/FinModAppPage.tsx``frontend/src/components/ReconWizard.tsx``frontend/src/components/Chart*.tsx``frontend/src/components/MarkdownEditor.tsx``frontend/src/hooks/**` |
| **C**    | **1** 模型配置联动**5** 登陆页面 ⚠️ | 模型与鉴权     | `routes/models.py``routes/workspace.py``routes/context.py``storage/model_store.py``agent/llm_client.py``agent/agent_config.py``agent/smol_model.py``frontend/src/pages/AiConfigPage.tsx``frontend/src/components/ModelPicker.tsx``ModelIcon.tsx` / `ModelCard.tsx` / `NewProjectDialog.tsx`                                                                                                        |
| **全员** | **4** 代码精简逻辑程度                | 横向重构       | ⚠️**不单独分工**，见第 7 节                                                                                                                                                                                                                                                                                                                                                                      |

**为什么 3 和 7 必须同一个人**：两个问题的端点都在同一个 3050 行的
`routes/apps.py` 里（recon 段 L494–810，finmod 段 L818–3050）。
分给两人 = 100% 冲突。

**为什么 1 和 5 可以给同一个人**：C 的领地集中在 `models.py` / `llm_client.py` / 配置页，
与 A、B 的领地几乎不重叠。

⚠️ **问题 5 需要先确认是否真要做** —— 见第 8 节。

---

## 4. 公用地雷（共享文件）

以下文件**多人需要改**，是冲突高发区。规则：**改动前先在群里说一声，改完立刻 push**。


| 文件                                     | 谁需要改                     | 冲突级别        | 应对                               |
| :----------------------------------------- | :----------------------------- | :---------------- | :----------------------------------- |
| `frontend/src/lib/api.ts`（≈1530 行）   | **所有人**（新增接口都要改） | 🔴🔴`100% 冲突` | ⚠️ 必须在**Phase 0** 拆分        |
| `routes/apps.py`（≈3050 行）            | B（主）+ C（模型解析）       | 🔴🔴            | ⚠️ 必须在**Phase 0** 拆分        |
| `agent/llm_client.py`                    | C（主）+ B（使用）           | 🔴              | C 拥有；B 只调用不改               |
| `frontend/src/components/FileEditor.tsx` | A + B                        | 🟡              | 改动前协调                         |
| `storage/schema.sql`                     | A（主）+ C（若要加用户表）   | 🟡              | 由 A 代为修改                      |
| `docs/项目架构文档.md`                   | 所有人（铁律 0）             | 🟡              | **只追加自己的章节**，不要重排全文 |
| `finance-agent-workbench/.github/**`     | ⚠️**禁止改**               | —              | 属项目铁律文件                     |
| `.gitattributes` / `.gitignore`          | ⚠️**禁止改**               | —              | 影响全体                           |

**铁律**：如果你需要改 `api.ts` 或 `apps.py` → **先停下来，找对应的人协调**，不要直接改。

---

## 5. Phase 0：前置解耦（必须最先做，否则无法并行）

这是**一切并行工作的前提**。不做这一步，三人开工第一天就会撞车。


| #   | 任务                                                                                         | 目标                           | 建议负责人 | 工作量    |
| :---- | :--------------------------------------------------------------------------------------------- | :------------------------------- | :----------- | :---------- |
| 0-1 | 拆分`routes/apps.py` → `routes/recon.py` + `routes/finmod.py` + `routes/_llm_report.py`     | 解开 问题3 ↔ 问题7 死锁       | B          | 0.5–1 天 |
| 0-2 | 拆分`frontend/src/lib/api.ts` → `lib/api/{models,data,recon,finmod}.ts` + barrel `index.ts` | 解开**全员**公共冲突           | C          | 0.5–1 天 |
| 0-3 | 抽出`agent/model_resolver.py`（含 `_build_llm_client` / `_resolve_model_ref`）               | 解开 模型领地 ↔ 报告领地 交叉 | C          | 0.5 天    |

**拆分原则**：

- **纯搬迁，不改逻辑**（一个提交只做移动，PR 里 diff 应显示"移动"而非"重写"）
- 拆分后立刻跑通验证：`python app.py` 启动 + `npm run build` 通过
- 拆完先合并进 `main`，三人再 `pull` 后各自开工

---

## 6. 日常协作流程

### 开工前（每个人、每次）

```bash
git checkout main
git pull                          # ① 先同步最新版
git checkout -b feat/B-3-xxx      # ② 从最新 main 开新分支
```

### 干活中

- 每隔半天 `git pull --rebase` 同步一次（避免攒太久）
- 改完一个**完整的小功能**就提交，不要攒一周

### 收工前

```bash
git status                        # ① 确认没误改别人领地的文件
python -m py_compile <改动的文件>  # ② 验证（前端用 npm run build）
git add -A
git commit -m "fix(3): 核对报告缺失分级说明"
git push -u origin feat/B-3-xxx
```

### 合并

1. GitHub 上开 **Pull Request**（`feat/B-3-xxx` → `main`）
2. **Description 里贴验证输出**（实际运行结果，不是「应该没问题」）
3. 另一个人看一眼（哪怕只是"没改我领地"）
4. Merge

### 每日同步节奏（建议）


| 时间   | 动作                                             |
| :------- | :------------------------------------------------- |
| 早     | `git checkout main && git pull`                  |
| 中午   | `git pull --rebase` + 汇报进展（谁在改哪些文件） |
| 下班前 | 提交 + push + 开 PR                              |

---

## 7. 问题 4（代码精简）的特殊处理

**问题 4 不能作为独立分工项。** 它本质是**横向重构**，会碰所有人的领地。


| 错误做法             | 正确做法                                 |
| :--------------------- | :----------------------------------------- |
| 安排一个人全库"精简" | ❌ 必然与另外两人 100% 冲突              |
| —                   | ✅ 各人在**改自己领地的 bug 时顺手精简** |
| —                   | ✅ 或作为 Phase 0 拆分的副产品           |

**精简时必须避开的雷区**（这些是"看起来冗余但必须存在"的代码）：


| 位置                                                       | 看似冗余       | 实际作用                                   |
| :----------------------------------------------------------- | :--------------- | :------------------------------------------- |
| `routes/apps.py::_fallback_report` / `_fallback_md_report` | 重复的报告模板 | LLM 不可用时的**降级路径**                 |
| `agent/llm_client.py::_build_body` 三家差异分支            | 重复代码       | 规避 deepseek/glm/qwen 真实**400 错误**    |
| `agent/llm_client.py::from_env`                            | 无人调用       | 环境变量**兜底路径**                       |
| `agent/core.py`（legacy AgentCore）                        | 已被 smol 取代 | ⚠️ 需**先确认无人依赖**再删（见第 8 节） |
| `tools/project_data_tools.py::_valid_columns`              | 简单函数       | 被`reconcile_tool.py` **跨文件 import**    |

**铁律**：删除任何函数前，必须执行 `git grep <函数名>` 确认全库无引用，
并在 PR 里贴出搜索结果。

---

## 8. 需要团队先决策的两件事

### ① 问题 5（登陆页面）—— 真要做吗？

**现状**：全库检索确认 **不存在任何登录/鉴权代码**
（无登录页、无 auth 路由、无密码校验、无路由守卫；`app.py` 页面路由全部直接放行）。

- 若**要做** → 属于**从零新增功能**，不是 bug 修复，工作量与其它 6 项不可比
- 若**不做** → 请从 `改进问题.md` 移除或标注「不适用」

**建议**：内网单机部署场景下，登录可能并非必需。**先确认需求再排期。**

### ② `agent/core.py`（legacy AgentCore）—— 能否删除？

项目存在双轨引擎：`smol_*.py`（现役）与 `core.py`（legacy，标记 DEPRECATED）。

- 若确认可删 → 问题 4 的最大收益点（约 1400 行）
- 需先确认：`agent/core.py` 是否仍被 `approval/` 或任何路由 import

---

## 9. 三大危险场景（实测结论）⚠️

以下三种操作会造成**静默的工作丢失**（无报错、代码照常运行）。
**实测环境**：Git 2.55，`ort` 合并策略。

### 场景 A：同名文件"删除重建" + 另一方修改


|       | 操作                                         |
| :------ | :--------------------------------------------- |
| Alice | 删掉`bug_a.py`，**同名**重建（内容全部换新） |
| Bob   | 修改`bug_a.py` 里的某一行                    |

**实测结果**：

- Git **完全不知道**这是"删除+新建"，只看到一次「修改」（`4 insertions(+), 6 deletions(-)`）
- Bob `pull` 时 → **`CONFLICT (content)`，整个文件冲突**（冲突标记包住全文）
- 若解决时随手取了 Alice 的版本 → **Bob 的修复瞬间消失，零报错**

### 场景 B：改名重建（内容不变）+ 另一方修改 → ✅ 安全


|       | 操作                                           |
| :------ | :----------------------------------------------- |
| Alice | `git mv bug_a.py bug_a_new.py`（**内容未变**） |
| Bob   | 修改`bug_a.py`                                 |

**实测结果**：Git 识别出改名（`rename bug_a.py => bug_a_new.py (100%)`），
**自动把 Bob 的改动搬到新文件名上**，零冲突。✅

### 场景 C：改名 + 大改内容 + 另一方修改 → 🔴🔴 最危险


|       | 操作                                            |
| :------ | :------------------------------------------------ |
| Alice | 删`bug_a.py`，新建 `bug_a_v2.py` 并**重写内容** |
| Bob   | 修改`bug_a.py`                                  |

**实测结果**：

```
CONFLICT (modify/delete): bug_a.py deleted in <Alice> and modified in HEAD.
Version HEAD of bug_a.py left in tree.
```

- Bob 改的文件被标记为「**被对方删除了**」
- 若 Bob 顺手 `git rm bug_a.py` + commit → **Bob 的修复静默消失**
- 实测确认：全库 grep 找不到 `FIXED-BY-BOB`，**无任何报错**

### 恢复手段（但需要你知道去找）

```bash
git log -S "被丢失的代码片段" --all     # 按内容搜索历史
git log --all --oneline -- <文件路径>    # 按文件搜索
```

> ⚠️ **前提是你知道要找**。若没人发现，损失就是永久的。

### 结论 → 三条硬规则


| #     | 规则                                                                 |
| :------ | :--------------------------------------------------------------------- |
| **1** | **要"重写"文件时，原地修改内容，绝不允许"删了再建"**                 |
| **2** | **若必须改名，先单独提交一次"纯改名"（不改内容），再另起提交改内容** |
| **3** | **解决冲突时，先读懂四方内容（用 `zdiff3`），默认"双方改动都保留"**  |

---

## 10. 冲突处理协议（强制执行）

### 一次性配置（每个人、每台电脑）

```bash
git config --global merge.conflictStyle zdiff3   # 冲突时显示 base 原始版本
git config --global diff.algorithm   histogram   # 更准确的内容匹配
git config --global rerere.enabled   true        # 记住冲突解法，下次自动复用
```

`zdiff3` 的效果（**强烈推荐**）：

```
<<<<<<< HEAD
L5-BOB              ← 我改成了这样
||||||| a6cc83c
L5                  ← 原来是这样   ← 关键！没有这行就只能靠猜
=======
A-INSERTED          ← 对方改成了这样
L5
>>>>>>> a5d654e
```

### 冲突处理四步

1. **`git status`** 看哪些文件冲突（`UU` / `UD` / `DU` / `AA`）
2. **读懂四方**：我的 / 原始（base）/ 对方的
3. **判断意图**：默认**双方都要保留**——冲突≠二选一，多数情况是把两处**并起来**
4. **解决后必须验证**：`git add <文件>` → 实际运行 / 编译 → `git commit`

### 冲突状态速查


| 状态 | 含义                 | 危险度          |
| :----- | :--------------------- | :---------------- |
| `UU` | 双方都改了同一区域   | 🟡 需人工合并   |
| `UD` | **对方删了，我改了** | 🔴🔴 极易丢工作 |
| `DU` | **我删了，对方改了** | 🔴🔴 极易丢工作 |
| `AA` | 双方都新建了同名文件 | 🔴              |

### 🚫 禁止的操作


| 禁止                                             | 后果                           |
| :------------------------------------------------- | :------------------------------- |
| 删掉冲突标记、只留一边                           | **丢掉另一方全部工作，零报错** |
| `git checkout --ours <文件>` / `--theirs` 一把梭 | 同上                           |
| `git push --force`                               | 覆盖他人提交                   |
| `git reset --hard`                               | 丢弃本地未提交改动             |
| 不确定时"猜一个"                                 | 隐藏 bug 进入主线              |

**不确定 → 停下来问人。** 这条永远优先于"完成任务"。

---

## 11. 换行符规范（已由 `.gitattributes` 强制）

**已解决**。仓库根目录的 `.gitattributes` 会把换行符统一为 LF 存入仓库。

**为什么重要**：Git 的合并是**按行内容匹配**。若同一文件在两人机器上换行符不同
（CRLF vs LF），Git 会认为**每一行都变了** → **整文件冲突**（改了 3 行却报 800 行冲突）。

**现状（已核实）**：仓库内 678 个文本文件全部为 `i/lf`（规范），工作区为 CRLF（Windows 正常）。
→ 该文件加入后**零破坏性**，且永久锁住这个好状态。

**不要修改 `.gitattributes`。** 需要变更请全员同意。

---

## 12. 事故预防速查表


| 危险动作                          | 会怎样                         | 正确做法           |
| :---------------------------------- | :------------------------------- | :------------------- |
| 删文件再新建同名文件              | 整文件冲突，易丢工作           | **原地改内容**     |
| 改名同时大改内容                  | `modify/delete` 冲突，静默丢失 | 分两次提交         |
| 全库"顺手格式化"                  | 假冲突淹没真实改动             | **只改必要行**     |
| 直接在`main` 上改                 | 冲突 + 影响他人                | 开`feat/` 分支     |
| 一周才 push 一次                  | 冲突面巨大                     | 每半天同步         |
| 改`api.ts` / `apps.py` 不打招呼   | 100% 冲突                      | **先协调**         |
| 冲突时只留一边                    | 静默丢失他人工作               | 读懂四方，两边都留 |
| 只说"已完成"                      | 问题被隐藏                     | **贴实际运行输出** |
| 改`.gitattributes` / `.gitignore` | 影响全体                       | 全员同意           |

---

## 13. 立项检查清单（正式开工前逐项确认）

- [ ]  三人各自设置好 `git config user.name/email`（区分提交作者）
- [ ]  全员执行冲突配置：`zdiff3` / `histogram` / `rerere`
- [ ]  仓库已加 `.gitattributes`（换行符统一）✅ 已完成
- [ ]  `main` 已开分支保护（禁止直接 push）
- [ ]  **Phase 0 解耦完成并合并进 `main`**（拆分 `apps.py` / `api.ts`，抽出 `model_resolver.py`）
- [ ]  三人已 `git pull` 拿到 Phase 0 结果
- [ ]  分工矩阵已确认，每人知道自己的**独占文件**与**禁区**
- [ ]  每人已把 `.github/copilot-instructions.md` 作为 AI 的必读上下文
- [ ]  **问题 5（登录）需求已确认**（做 / 不做）
- [ ]  `agent/core.py` 是否可删已确认
