# readouts：round 1 投票保留多数细节，round 5 卡住的折叠改为裁决

计划日期 2026-11-02。结论见 `docs/readouts_vote_and_fold_adjudication_2026-11-02.md`。

## Context

两份独立 review 都落在 `readouts` 上，它是 schema 里最不稳的自由文本字段（三份抽取全同 45/173，而 technique 和 sample_type ≥ 161/178）。但两份看的是不同轮次，方向相反：

- **round 1 投票**（`apps/api/app/agent/assay_consensus.py:_vote_text`）：三份两两宽松一致时交付最短的那份。复核 v3 存盘回复：178 个交付簇中 readouts 逐字多数 110、宽松档 66、兜底 2。宽松档里"最短者胜"把两份都写了的细节丢掉（SDY1289 "gene expression levels" 丢了 whole-blood + Illumina BeadChips）。readouts 越泛，round 5 越容易把两个不同测量判成"不冲突"。
- **round 5 折叠**（`apps/api/app/agent/assay_merger.py:_refusal`）：readouts 规范化后严格相等才允许折。v3 全语料 22 个 blocked fold，14 个卡在 readouts。把投票的宽松匹配搬过去只放开 1 个（SDY1291），说明这条腿是二值的，没有阈值可调。
- 为什么不拿掉 readouts：`_refusal` 按 technique → sample_type → readouts 查，卡在 readouts 的 14 对前两条腿本就相同，拿掉即全部折叠。对照 `data/benchmark_assay/benchmark_assay_v5/`，这些正是策展人分成两行的：SDY1328 GM1-ELISA 对 multiplex ELISA；SDY1288 IgM capture ELISA 对 Inhibition ELISA；SDY1640 flow cytometry / ICS / AIM 三行；SDY1630 flow cytometry 对 functional assays；SDY212 两个 flow 条目。同一台流式仪、同一管 PBMC 跑表型、ICS、磷酸化三个测量，只有 readouts 把它们分开。宽松规则只放开 1 个，说明 14 对里只有 1 个是措辞问题，其余是真差异。

取各自合理的部分：
1. round 1 决胜改成"保留多数细节"（免费、确定性、可在存盘回复上度量）。
2. round 5 **不再找字符串规则**，readouts 留在三元组里；卡住的对子花一次调用裁决，先作为实验在存盘注册表上跑完、对 benchmark 打分，再决定是否成为默认链的一部分。

## 第一部分：round 1 决胜规则（免费）

`assay_consensus._vote_text` 宽松档的打分键改为 `(-agree_count, -shared_tokens, len, i)`：先取与其他值共享内容词最多的那份，再取最短，再按 anchor 顺序。只有一份加的词仍然进不来；两份都写的细节留下。

度量脚本 `experiment/readouts_vote_medoid/run.py`：重投 v3 三份回复，列出改前/改后交付值；把新 readouts 替换进各目录 `assays.json`（仅当现值等于旧投票值，round 3 的更正不覆盖），用 `canonical_groups` 重算 blocked fold。

测试 `apps/api/tests/test_assay_consensus.py`：两份共有细节保留的用例；一份独有细节仍不进的用例。

## 第二部分：round 5 卡住折叠的裁决（先实验，再决定）

不改 `_IDENTITY_FIELDS`、`_differs`、`_refusal`。

新模块 `apps/api/app/agent/assay_fold_judge.py`：`adjudicate(assays, obi, judge)` 对每个 blocked fold 中仅差 readouts 或 sample_type 的对子调一次模型（提示词 `apps/api/app/prompts/judge_fold.txt`），technique 不同的不送。`SAME` 经 `merge_entries` 折叠并在 `assays_merges.json` 记 `judged`；`DIFFERENT` 保留为 `REVIEW  not folded` 并附理由；无法解析的回复按 DIFFERENT 处理。回复记入 `assays_raw.json` 的 `judge`。

实验脚本 `experiment/fold_adjudication/run.py`：`--dry-run` 报对子和调用数；付费跑在 `runs/` 副本上，再用 `scripts/compare_assay_benchmark_v2.py --registry-dir` 打分。

接入决定：benchmark 净收益 ≥ 0 且没有把 SDY1328、SDY212、SDY1630 等真差异判成 SAME，才接到 `assay_service.py` round 5 和 `estimate_run`；否则不接入，22 个 REVIEW 行即最终状态。

## 不做的事

- 不把 readouts 从三元组里拿掉。
- 不给 round 5 加任何宽松字符串匹配。
- 不重跑任何论文的 round 1–4；付费裁决先 `--dry-run` 报数、等用户点头。
