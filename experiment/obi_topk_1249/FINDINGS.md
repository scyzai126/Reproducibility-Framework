# 词表 × 候选列表宽度 的 2×2 实验(31 篇 benchmark,round 4 only)

2026-11-10。产物全部在 `experiment/obi_topk_1249/`,未改动任何现有实验目录、`data/` 或结果盘。

## 设计

同一批输入(`data/benchmark_agent_assays/assay_result_v3` 的 31 个 registry 的 `assays.json`),
同一评分器(`scripts/compare_assay_benchmark_v2.py` 对 benchmark v5),只变两个变量:

- **词表**:701(现行 pruned)vs 1249(noncompositional,只去 compositional、保留 domain)
- **K**:20(现行)vs 30(paper-wording 保留槽位同比缩放 14/20 → 21/30)

**功能集必须对齐。** 2026-10-27 跑的三个 K=20 臂早于全词表兜底(`_fulllist_pick`)功能,
在该位置记为 `unresolved`;本次两个 K=30 臂都触发了 2 次 `fulllist_llm`。
下表为把兜底结果还原成 `unresolved` 后的可比数值,四个格子的 `resource` 分布完全一致。

## 结果

| 臂 | exact | OBI ok | CONFLICT | UNMAPPED | obi_recall |
|---|---|---|---|---|---|
| 701 @ K=20(现行) | 141 | 145 | 5 | 6 | 92.4% |
| 701 @ K=20 第二次跑(噪声参照) | 140 | 145 | 5 | 6 | 92.4% |
| 1249 @ K=20 | 140 | 144 | 6 | 6 | 91.7% |
| 1794 @ K=20 | 130 | 139 | 10 | 7 | 88.5% |
| **701 @ K=30** | **139** | 143 | 7 | 6 | 91.1% |
| **1249 @ K=30** | **142** | **146** | **4** | 6 | **93.0%** |

exact 的 2×2:

| | K=20 | K=30 | ΔK |
|---|---|---|---|
| **701** | 141 | 139 | **-2** |
| **1249** | 140 | 142 | **+2** |
| Δ词表 | -1 | **+3** | |

**两个变量交互,符号相反,不可加。** 加宽 K 在小词表上有害、在大词表上有益。

## 机制(逐条 diff)

701 @ K=20 → K=30,多出来的 10 个槽位把 picker 引向更粗或旁系的 term:

| entry | K=20 | K=30 | curator |
|---|---|---|---|
| SDY1293 实时RT-PCR | OBI:0000911 ✓ | OBI:0000893(实时PCR,变粗) | OBI:0000911 |
| SDY1293 microscopy | OBI:0002119 ✓ | OBI:0003038(寄生虫检测,旁系) | OBI:0002119 |
| SDY1276 SNP芯片分型 | OBI:0002031 ✓ | OBI:0001274(芯片分型,变粗) | OBI:0002031 |
| SDY1260 CBA | OBI:0000920 | OBI:0003116 ✓ | OBI:0003116 |

701 @ K=30 → 1249 @ K=30,上述三条全部被纠正,另加一条新增:

| entry | 701@30 | 1249@30 | curator |
|---|---|---|---|
| SDY1293 实时RT-PCR | OBI:0000893 | OBI:0000911 ✓ | OBI:0000911 |
| SDY1293 microscopy | OBI:0003038 | OBI:0002119 ✓ | OBI:0002119 |
| SDY1276 SNP芯片分型 | OBI:0001274 | OBI:0002031 ✓ | OBI:0002031 |
| SDY1264 RT-PCR | OBI:0001170 | OBI:0000911 ✓ | OBI:0000911 |
| SDY1260 CBA | OBI:0003116 ✓ | OBI:0000920 | OBI:0003116 |

唯一退步的 SDY1260 与阶段一的免费 recall 预测一致:`OBI:0003116` 不在 1249@K=30 的候选列表上。

## 可以下的结论 / 不能下的结论

噪声参照:同一配置跑两次 exact 为 141 / 140,逐条 diff 变 2 条,所以噪声带约 ±1~2。

**站得住:**
- 固定 K=30,**1249 比 701 高 3 条**,超出噪声带。
- **不能只把 `TOP_K` 从 20 改成 30 而不动词表** —— 在现行 701 上这么做是 **-2**,方向明确且机制自洽(3 条都是被更粗/旁系 term 引走)。
- 1794 全词表在任何配置下都差得多(130),compositional prune 必须保留。

**站不住:**
- **1249 @ K=30(142)对现行 701 @ K=20(141)只高 1 条,在噪声带内,未达成 exact ≥ 143 的判据。**
  它在每一列上都不差于现行(CONFLICT 4 为全场最低,OBI ok 146 与 recall 93.0% 为无兜底组最高),
  方向一致,但 31 篇、±2 噪声的 benchmark 分辨不出这个量级。

## 这个 benchmark 测不到的部分

31 篇的 assay 几乎全在 OBI 覆盖内(`unresolved` 仅 2 条),所以它对**覆盖率**和
**family 被切坏**结构性失明。语料侧已实测的 stage-2 硬损害(892 篇,见计划工作项 0):
2 条 Hi-C 被错映射成 5C-seq、4 条 UNMAPPED(cell migration ×3、SAXS ×1)。
这 6 条只偏向 1249 或偏向定点白名单,在本实验里不可能出现。

## 文件

```
run_recall_1249.py            阶段一,免费离线重放 recall@K
run_pick_1249.py --arm --k    阶段二,round 4 picker
recall/comparison.md          701 vs 1249 的 recall@K 对照
recall/findings.md            阶段一结论
picks/k30/                    1249 @ K=30(原始,含兜底)
picks/k30_nofallback/         同上,兜底还原为 unresolved ← 可比
picks/k30_701/                701  @ K=30(原始,含兜底)
picks/k30_701_nofallback/     同上 ← 可比
```
