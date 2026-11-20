# 用 Claude 跑 5 篇 benchmark,和现有 GPT 结果对比

## Context

用户想知道把 assay 链路的模型从 gpt-5.4 换成 Claude 后结果差多少。只跑 Claude,不重跑 GPT;
对照是现有的 `data/benchmark_agent_assays/assay_result_v3/`(strict:144 exact,F1 0.934)。

现状:整条链路只通过 `client.chat.completions.create(...)` 调 OpenAI,读
`resp.choices[0].message.content` 和 `resp.usage`,没有统一封装。`ANTHROPIC_API_KEY` 已在
`.env` 和 `Settings` 里,但没有代码用它,`anthropic` 包也没装。

## 默认选择(批准前可改)

- **模型:`claude-opus-5-5`**($4/$20 每百万 token),effort 显式设为 `medium`(该模型默认值)。
  想用 Sonnet 5.5 或 Fable 5.2 只需换环境变量,代码不变。
- **5 篇(全部 XML,难易混合)**:
  `23266342_SDY1364`(最小,3 行)、`23601689_SDY180`(v3 满分 6/6)、
  `26742691_SDY1328`(v3 多 1 条)、`28854372_SDY1373`(v3 只有 2/4 exact)、
  `32788292_SDY1669`(9 行,v3 漏 1 条)。
- **预估费用**:每篇约 21–25 次调用、约 20 万输入 token,5 篇合计约 $5–8(不含 thinking token)。

## 代码改动

1. **新文件 `apps/api/app/agent/anthropic_chat.py`** — 一个外形像 OpenAI client 的适配器,
   底层用官方 `anthropic` SDK:
   - `AsyncAnthropicChat` / `AnthropicChat`,各暴露 `.chat.completions.create(**kw)`。
   - 请求转换:丢弃 `seed`、`prompt_cache_key`、`temperature`(Opus 5.5 传采样参数会 400);
     `system` 消息移到顶层 `system`;加 `max_tokens=16000`、
     `output_config={"effort": "medium"}`、顶层 `cache_control={"type": "ephemeral"}`。
   - 回复转换:返回带 `.choices[0].message.content`(拼接所有 text block)和 OpenAI 形状
     `usage` 的对象:`prompt_tokens = input + cache_read + cache_creation`、
     `prompt_tokens_details.cached_tokens = cache_read`、`completion_tokens = output_tokens`,
     这样 `assay_trace.usage_fields` 和 ledger 不用改。
   - `stop_reason` 为 `refusal` 或 `max_tokens` 时抛异常,让链路按现有逻辑记成 ERROR,
     而不是把截断的回复当结果。**不开 server-side fallback**:回退到别的模型会污染对比。
   - 遇到 PDF `file` part 直接 `NotImplementedError`(这 5 篇都是 XML,PDF 路线不做)。
   - `is_claude(model)`:`model.startswith("claude")`。
2. **三处注入**(模型名是 `claude*` 时用适配器,否则原样构造 OpenAI,现有测试的 patch 点不变):
   - `scripts/run_assay_pipeline.py:422` — 传给 `assay_report` 的 async client(轮 1–3)。
   - `apps/api/app/agent/assay_obi_mapper.py:475`、`:699` — OBI pick / full-list pick。
     **`:315` 的 embedding 不动,仍用 OpenAI `text-embedding-3-small`**(磁盘上的 OBI 向量是它算的)。
   - `apps/api/app/agent/assay_fold_judge.py:101` — 轮 6 judge。
3. **`apps/api/app/agent/assay_trace.py`** — `LIST_PRICE_USD_PER_MTOK` 加一行
   `claude-opus-5-5: input 4.00 / cached 0.20 / output 20.00`,否则 ledger 的美元列为空。
4. **`requirements.txt`** 加 `anthropic`,并装进仓库根 `.venv`。
5. **新测试 `apps/api/tests/test_anthropic_chat.py`** — 用假 Anthropic client 覆盖:参数丢弃、
   system 提升、usage 映射、refusal/max_tokens 抛错、PDF part 报错、`is_claude`。

模型名沿用现有机制:运行时设环境变量 `OPENAI_MODEL=claude-opus-5-5`(pydantic 优先读环境变量,
各轮的默认参数在 import 时取它),不改 `.env`。

## 运行步骤

1. 新建分支 `feature/claude-assay-arm`;把本计划另存到 `docs/plan/claude_vs_gpt_assay_plan.md`。
2. 实现上述改动,在 `apps/api/` 跑 `pytest`(基线:10 个既有失败,不应新增)。
3. 用 `client.models.retrieve("claude-opus-5-5")` 验证 key 可用(免费)。
4. 对 5 篇各跑一次 `--dry-run`(免费),汇报调用数估计,**停下等用户放行**(CLAUDE.md 要求)。
5. 放行后逐篇运行完整投票链路:
   `OPENAI_MODEL=claude-opus-5-5 .venv/bin/python scripts/run_assay_pipeline.py --pmid <pmid> --sdy <SDY> --result-version claude_opus_5_5_v1`
   输出到 `data/benchmark_agent_assays/claude_opus_5_5_v1/<pmid>_<SDY>/`,不触碰 v1/v3。
   逐字汇报每篇的 `WARNING` / `REVIEW` / `JUDGED` / `REJECT` / `DROPPED` / `MINORITY` / `VOTE` /
   `MERGED` 行和用量块。
6. 打分(免费,不调模型),default 和 strict 各一次:
   `scripts/compare_assay_benchmark_v2.py --registry-dir data/benchmark_agent_assays/claude_opus_5_5_v1 [--strict]`
   GPT 侧从 `assay_result_v3/comparison/benchmark_vs_agent{,_strict}.json` 里取同 5 篇的 metrics。
7. 写 `docs/claude_vs_gpt_assays_2026-11-16.md`:5 篇合计与逐篇的
   matched / exact / missed / extra / precision / recall / F1 对照,逐条列出两边不同的条目
   (只有一边有的 assay、OBI term 不同的、fold 不同的),以及 Claude 的调用数、token、费用。

## 对比的已知局限(会写进报告)

- **prompt 不完全相同**:v3 是用旧版 `extract_assays.txt` 跑的,之后有未提交的改动(单细胞/受体
  测序规则)。差异里会混入这部分影响。
- **v3 的轮 4–6 是后来重映射的**(1249 词表、TOP_K 30),和现在的代码一致。
- Opus 5.5 不能设 temperature/seed,三次抽取本来就不确定;只跑一遍,5 篇样本小,结论是方向性的。
- v3 没有 token 记录,成本只能和 ledger 里 v4 的 SDY1669(gpt-5.4,$0.36)对一篇。
- Claude 的缓存只对完全相同的请求生效(三次抽取调用),verify/correct 的共享前缀不会命中,
  所以 Claude 的费用偏高,不代表优化后的成本;cache 写入的 1.25 倍溢价不计入估算。

## 验证

- `pytest` 全套,新测试通过,失败数仍为 10。
- `git status` 列出改动文件:只应有上面 5 个代码/依赖文件、新结果目录、两份文档和 ledger 新行。
- 5 个结果目录都有 `assays_benchmark.json`;scorer 输出 5 篇被配对、其余 26 篇 `SKIPPED`。

## 执行记录(2026-11-16)

用户放行时把模型改成了 `claude-fable-5-2`,结果目录为 `data/benchmark_agent_assays/claude_fable_5_2_v1/`,
`assay_trace.LIST_PRICE_USD_PER_MTOK` 另加了 Fable 5.2 的价格行。结果见 `docs/claude_vs_gpt_assays_2026-11-16.md`。
