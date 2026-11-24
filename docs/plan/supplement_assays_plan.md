# 31 篇 benchmark 文章的 supplementary：下载、找 supplementary methods、找多出来的 assay

## Context

现在的 assay 链只读正文：`jats_parser.py` 故意丢掉 `<supplementary-material>` 和标题含 supplementary 的 section，而且 XML 里这些元素只有文件名和标题，没有正文。所以 supplement 里的方法从来没进过提取器。问题是：31 篇里哪些有 supplement、能不能下载、里面有没有 supplementary methods、有没有正文和 curated benchmark 都没有的 assay。

已查到的现状（27 篇有 XML，4 篇只有 PDF）：

- 25 / 27 篇 XML 列出了 supplement 文件；SDY1364 (23266342) 没有；SDY1669 (32788292) 只有 Science 网站的 `suppl/DC1` 链接，而且 XML 里根本没有 Methods section。
- 正文明确指向 supplement 方法的：SDY1264、SDY180、SDY1373（"Supplementary Methods" / "Supplemental Experimental Procedures"），SDY1260（Supplementary Note），SDY1393、SDY1288（Appendix），SDY1669（全部方法在 supplement）。
- 4 篇 PDF-only（SDY1293、SDY1276/21357945、SDY1291、SDY404）没有 XML，要先用 idconv 查 PMCID 才知道。
- 仓库里没有任何下载 supplement 的代码；curated benchmark v5 的 138 条 evidence 没有一条引自 supplement。

## 做法：三个阶段，前两个免费，第三个付费且要先等确认

### 阶段 1（免费）— 清点并下载

新模块 `apps/api/app/agent/paper_supplements.py` + 脚本 `scripts/download_paper_supplements.py`。

1. 文章清单用 `data/benchmark_agent_assays/assay_result_v3/` 的 31 个文件夹（`assay_service.split_stem`）。PMCID 从 XML 的 `<article-id>` 取；4 篇 PDF-only 用 `ncbi_utils` / `immport_corpus.IDCONV_URL` 查。
2. 从 XML 列出 supplement 文件：`<supplementary-material>` 和裸的 `<media>`（BMC 的 SDY1325 只用后者）的 `xlink:href` + caption。
3. 下载，按顺序尝试，第一步先只拿 1 篇验证哪条路通：
   - Europe PMC `https://www.ebi.ac.uk/europepmc/webservices/rest/<PMCID>/supplementaryFiles`（一个 zip，含 author manuscript 的 NIHMS 文件）
   - PMC `https://pmc.ncbi.nlm.nih.gov/articles/<PMCID>/bin/<href>`
   - NCBI OA 包 `oa.fcgi?id=<PMCID>`（只对 OA 子集）
   - 复用 `download_pmc_corpus._params` / `request_delay` 的限速；User-Agent 用通用名，不带邮箱。
4. 写到 `data/supplements/<SDY>_<pmid>/files/`，每篇一个独立目录（下载物当不可信数据，zip 只解出普通文件、检查路径）。汇总 `data/supplements/manifest.csv`：文章、文件名、类型、大小、来源 URL、状态（ok / 无 supplement / 下载失败 / 需手动）。
5. 预期要手动的：SDY1669（science.org 大概率挡脚本）和没有 PMCID 的 PDF-only 文章 —— manifest 里标 `manual`，给出链接，放进同一目录后重跑即可接上。

### 阶段 2（免费）— 抽文字、找 supplementary methods

1. PDF 用现有 `paper_reader.extract_pdf_text`（PyMuPDF）；docx 读 `word/document.xml`；xlsx / 图片 / 数据 zip 不读，只记在 manifest。
2. 按标题行切块，标题匹配 `Supplementary/Supplemental (Materials and) Methods`、`Experimental Procedures`、`Materials and Methods`、`Online Methods`、`Supplementary Note`、`Appendix` 的块标 `[methods]`，其余（图注、表注）标 `[other]`。
3. 写成和 `parse_jats_xml` 相同的格式（`## 标题  [bucket]` + `jats_parser.number_sentences` 的 `[S<n>]`），存 `data/supplements/<SDY>_<pmid>/supplement.txt`。这样 `has_methods_section`、`derive_evidence_fields` 不用改。
4. 报告每篇：有无 supplement、下载到几个文件、有无文字、有无 supplementary methods 及其字数。**到这里停下来汇报。**

### 阶段 3（付费，先 `--dry-run` 等确认）— 在 supplement 文字上跑完整的 voted 链，再比对

> **2026-11-20 改为另一种做法，本阶段没有按下面的写法实现。** supplement 不单独跑，而是接在正文后面作为一份文档跑一次链：`scripts/run_assay_pipeline.py --supplement`。见 `docs/plan/assay_supplement_workflow_plan.md`。

1. 只跑阶段 2 判定为「有 supplementary methods」的文章（估计 7–12 篇，不是 31 篇）。
2. 新脚本 `scripts/run_supplement_assays.py`：仍然走 `assay_service.assay_report`（三次提取投票 → verify → correct → OBI → canonicalize → judge，不新增单次提取路径），只是把论文来源换成 `supplement.txt`。为此给 `assay_report` 加一个可选参数 `source_text=None`（传入时跳过 `locate_paper_source`），这是对核心代码唯一的改动。
3. 结果写到新的 result version `data/benchmark_agent_assays/assay_result_v3_supplement/<pmid>_<SDY>/`，不动 v3 的正文结果。ledger 照常记一行。
4. 费用：正文一篇中位数 12 次调用 / $0.21，最大 $1.18；supplement 一般比正文短，10 篇左右约 $2–5。先报 dry-run 的调用数。
5. 比对（免费，不调用模型）`scripts/compare_supplement_assays.py`：supplement 的每条 assay 对照 (a) v3 正文的 `assays_benchmark.json`，(b) `data/benchmark_assay/benchmark_assay_v5/`。匹配规则复用 round 5 的同一测量判定（同 `obi_id` + technique / sample_type / readouts 三元组，`assay_merger`），再加名字/alias 重合。每条归为：
   - 正文已有
   - 正文没有、curated benchmark 有（supplement 帮 agent 补上的 recall）
   - **两边都没有 = 只在 supplement 里的 assay**
6. 产出 `data/supplements/supplement_only_assays.json` 和 `docs/supplement_assays_2026-11.md`（每篇一张表，带 quote）。脚本打印的 `WARNING / REVIEW / JUDGED / REJECT / DROPPED / MINORITY / VOTE / MERGED` 行原样报告。

## 改动的文件

- 新：`apps/api/app/agent/paper_supplements.py`、`apps/api/tests/test_paper_supplements.py`
- 新：`scripts/download_paper_supplements.py`、`scripts/run_supplement_assays.py`、`scripts/compare_supplement_assays.py`
- 改：`apps/api/app/agent/assay_service.py`（`assay_report` 的 `source_text` 参数）+ `tests/test_assay_service.py` 加一个用例
- 新文档：`docs/plan/supplement_assays_plan.md`（本计划的副本）、`docs/supplement_assays_2026-11.md`
- 下载的二进制文件不提交，只提交 manifest 和 `supplement.txt`。

## 验证

- 单元测试（不联网、不调模型）：XML → supplement 文件列表（含 BMC 裸 `<media>`、SDY1669 无 href 的情况）、zip 安全解包、标题分桶、输出格式能被 `has_methods_section` 和 `sentence_sections` 读回、`assay_report(source_text=…)` 用 stub client 跑通。
- `cd apps/api && ../../.venv/bin/pytest`；已知的 10 个 subject-query 红测试是基线。
- 阶段 1 先拿 SDY1373（`mmc1.pdf` 明确含 Supplemental Experimental Procedures）跑通下载和抽字，再放开 31 篇。
- 阶段 3 先 `--dry-run`，确认后先跑 SDY1669（正文无 Methods，最可能有新 assay）一篇看结果，再跑其余。
