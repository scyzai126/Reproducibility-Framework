# 新 workflow：正文 + supplement 一起提取 assay（现有 workflow 原样保留）

## Context

现在的 assay 链只读正文：`jats_parser` 丢掉所有 supplementary 容器，XML 里也只有文件名。方法写在 supplement 里的文章（SDY1669 全部方法都在 supplement；SDY1373、SDY1393、SDY1288 等有 Supplementary Methods）因此漏 assay。supplement 的下载和抽字已经建好并提交（`paper_supplements.py`、`data/supplements/<SDY>_<pmid>/supplement.txt`），但还没接进提取链。

用户的要求：**现有的 workflow、prompt、结果一律不动**；另建一条新 workflow 和新 prompt，把正文和 supplement 一起读。

结果：同一条 voted 链（提取×3 投票 → verify → correct → OBI → canonicalize → judge）多一个 `--supplement` 开关。不加开关时，prompt 文本、缓存 key、输出目录和现在逐字节相同。

## 设计

### 1. 合并文档（新模块 `apps/api/app/agent/assay_supplement.py`）

`combined_source_text(xml_path, supplement_path) -> (title, text, first_supplement_id)`

```
<正文：parse_jats_xml 的输出，原样>
--- Supplement ---
## mmc1.pdf: Supplemental Experimental Procedures  [methods]
...
## mmc1.pdf  [other]
...
```

- 正文在前、supplement 在后，拼好后**统一跑一次** `jats_parser.number_sentences`。计数器只有一个，所以正文每句的 `[S<n>]` 和现有 workflow 里完全一样，两边结果可以按句子 id 直接对比。
- supplement 文本取自磁盘上的 `supplement.txt`，用 `jats_parser.strip_sentence_ids`（`number_sentences` 的精确逆运算）去掉它自己那套编号。
- `--- Supplement ---` 这一行不用新代码支持：`_STRUCTURAL` 已经把 `--- ` 开头的行当结构行（不编号），`sentence_sections` 遇到后面的 `## … [methods]` 标题会把 bucket 重新设成 `methods`。所以 `source` 的推导、verifier 的引文核对、`locate_sentence_ids` 都不用改。
- **喂入范围**：methods 块在前，其余块（补充图注、表注）在后，supplement 部分总长上限 `SUPPLEMENT_MAX_CHARS = 40_000`（常量，可调）。`paper_supplements.render` 已经是 methods 优先的顺序，截断只会切到图表说明。正文仍按原来的 12 万字符上限。理由：标题正则可能漏判 methods，留一部分额度给其余文字；v3 的两条 strict 漏检引用的正是补充图（fig. S16A、Extended Data Fig. 7）。

### 2. 新 prompt `apps/api/app/prompts/extract_assays_supplement.txt`

以 `extract_assays.txt` 为底稿复制一份再改，原文件不动。只改和文档结构有关的部分，entry 规则、七个字段、输出格式保持一致（这样两条 workflow 的结果可比）：

- "The source text"：说明 `--- Tables ---` 之后还有 `--- Supplement ---` 块，标题形如 `## <文件名>: <标题>  [methods]` 或 `[other]`；supplement 的 `[other]` 是补充图注和表注，按 captions 对待，不是 Results。
- 删掉 "supplementary containers … are already removed"。
- Pass 1 的范围改成正文 `[methods]` **加上** supplement `[methods]`；同一技术在两处都写了只出一条，另一处的叫法进 `aliases`，quote 取描述更完整的那句。
- Structure 3 改成"正文和 supplement 都没有 `[methods]`"才适用；正文没有 Methods 但 supplement 有的，按 structure 1/2 走。
- `evidence.section` 照抄标题原文（supplement 的含文件名）。

新模块里的 `build_supplement_prompt` 用新文件；"有没有 Methods"在整份合并文本上判断（现有 `methods_chars` 只数 `--- Figures ---` 之前，不能直接用，新模块里写一个数全文的版本）。`extract_assays_with_supplement(...)` 仿照现有 `assay_extractor_pdf.py` 的做法：独立的提取函数，trace 里记 `source_kind="xml+supplement"`，回复仍经 `assay_extractor.parse_registry_json` / `clean_registry`。

verify 和 correct 的 prompt 两条 workflow 共用：它们拿到的是整份 `source_text`，没有"只有正文"的措辞（实现时再通读一遍 `verify_assays.txt` 确认，若有再另存一份 `_supplement` 版，不改原文件）。

### 3. 链路接入（`assay_service.py`，默认路径不变）

- `assay_report(..., supplement: bool = False)`：为 True 时
  - 只接受有 XML 的文章；没有 XML（4 篇 PDF-only）或没有 `supplement.txt` 时抛 `PaperNotFoundError`，说明缺哪一个。不静默退回正文 workflow。
  - `source_text` 换成合并文本；`kind` 仍是 `"xml"`（句子 id、`derive_evidence_fields`、`contract_warnings` 的现有分支照常走）。
  - `out_dir` = `SUPPLEMENT_REGISTRY_ROOT / "<pmid>_<SDY>"`，其中 `SUPPLEMENT_REGISTRY_ROOT = CORPUS_ROOT / "assay_supplement_v1"`。正文结果（`assay_result_v3` 等）不会被读写。
- `_run_rounds` 多收一个 `extractor` 参数，默认 `extract_assays`；round 1 的 XML 分支调 `extractor(...)`。这是 `_run_rounds` 唯一的改动。
- **来源标记**：promote 之前调 `assay_supplement.mark_supplement_evidence(assays, first_supplement_id)`，给 `evidence`（以及 `additional_evidence` 里每一条）加 `in_supplement: true/false`，由句子 id 用代码算出，不问模型。只在新 workflow 的输出里出现；`trim_registry` 把 `evidence` 整个带过去，所以 `assays_benchmark.json` 里也有。
- `estimate_run(..., supplement=False)`：`source_chars` 报合并后的长度；新目录里还没有上次结果时，用正文 registry 的形状估 round 2–6 并标明 basis。

### 4. 命令行（`scripts/run_assay_pipeline.py`）

- 新增 `--supplement`。不加时行为不变。
- 加上后：`--dry-run` 和正式跑都走新 workflow，输出目录固定在 `assay_supplement_v1/`（可用现有的 `--result-version` 改名）。
- 结果打印沿用现有的 `report_result`，另加一种 `SUPPLEMENT  <key>` 行：所有 evidence 都在 supplement 里的 entry，也就是只读正文不可能有依据的 assay。这是新 workflow 的主要产出，和 `WARNING / REVIEW / JUDGED / REJECT / DROPPED / MINORITY / VOTE / MERGED` 一样逐行报告。

### 5. 评估（免费）

- `scripts/compare_assay_benchmark_v2.py --registry-dir data/benchmark_agent_assays/assay_supplement_v1 --strict`，和 v3 的同一批文章比 recall / precision。
- curated benchmark v5 的 138 条 evidence 没有一条引自 supplement，所以只在 supplement 里的 assay 在 strict scorer 下会算成 false positive。因此 precision 要分两个数报：全部 entry，以及去掉 `SUPPLEMENT` entry 之后的；`SUPPLEMENT` entry 单独列表（带 quote）供人工判断。
- 写 `docs/assay_supplement_workflow_2026-11.md`。

## 改动的文件

- 新：`apps/api/app/agent/assay_supplement.py`、`apps/api/app/prompts/extract_assays_supplement.txt`、`apps/api/tests/test_assay_supplement.py`
- 改：`apps/api/app/agent/assay_service.py`（`supplement` 参数、`extractor` 参数、`SUPPLEMENT_REGISTRY_ROOT`）、`scripts/run_assay_pipeline.py`（`--supplement`、`SUPPLEMENT` 行）
- 文档：本计划存一份到 `docs/plan/assay_supplement_workflow_plan.md`；`docs/plan/supplement_assays_plan.md` 的阶段 3 加一行指向新计划；`CLAUDE.md` 的 assay 段落加一条 `--supplement` 说明
- 不动：`extract_assays.txt`、`extract_assays_pdf.txt`、`assay_extractor.build_prompt`、verifier、corrector、merger、ImmPort corpus runner、web 前端、已有的任何结果目录

复用：`jats_parser.number_sentences` / `strip_sentence_ids` / `sentence_sections`、`paper_supplements.SUPPLEMENT_ROOT` 和 `render`、`assay_service.locate_paper_xml` / `paper_source_text` 的解析方式、`assay_extractor.parse_registry_json` / `clean_registry` / `paper_cache_key`、`assay_verifier.derive_evidence_fields`。

## 验证

单元测试（不联网、不调模型），`cd apps/api && ../../.venv/bin/pytest`：

- 合并文本里正文部分的每个 `[S<n>]` 与 `paper_source_text` 的输出一致；supplement 的句子接着编号。
- `sentence_sections` 把 supplement 的 methods 句映射到 `methods`，`derive_source` 得到 `methods`。
- `first_supplement_id` 和 `mark_supplement_evidence`：正文引文 `false`，supplement 引文 `true`，`additional_evidence` 也被标。
- supplement 超过上限时截断在 `[other]` 块，methods 完整。
- `build_supplement_prompt`：正文无 Methods 而 supplement 有时不加 STRUCTURE 3 提示；两处都没有时加。
- **现有路径不变**：`assay_extractor.build_prompt` 的输出与改动前逐字节相同；`assay_report(...)` 不带 `supplement` 时用的是 `extract_assays`、写的是原目录。
- `assay_report(supplement=True)` 用 stub client 跑通：写到 `assay_supplement_v1/`，原 registry 目录的文件没有被碰；没有 `supplement.txt` 或只有 PDF 时抛 `PaperNotFoundError`。
- 已知的 10 个 subject-query 红测试是基线。

付费运行（按 CLAUDE.md，先 dry-run 再等确认）：

1. `scripts/run_assay_pipeline.py 28854372_SDY1373 --supplement --dry-run`，报调用数。
2. 确认后只跑 SDY1373 一篇（supplement 里有明确的 Supplemental Experimental Procedures），逐行报告全部输出，对照它在 v3 的正文结果。
3. 再确认后，跑其余有 supplementary methods 的文章（现在是 SDY1288、SDY1393、SDY2480、SDY2577、SDY2797；手动下载的文件到位并重新抽字后会增加）。
4. 跑 scorer，写结果文档。
