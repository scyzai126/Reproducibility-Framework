# 阶段一结论:加宽 K 不能填平 1249 相对 701 的检索劣势

2026-11-10。免费离线重放,未调用任何 API(query 向量取自
`experiment/obi_topk/query_embeddings.json` 的 193 条缓存,term 向量取自各臂的 embeddings 文件)。
168 条带 curator OBI term 的 entry。

## 假设

1249 在 31 篇 benchmark 上唯一输掉的一条(SDY1293 `microscopy assay`),失败机制是
8 个 `OBI:21xxxxx` 临床化验板 term 占满了 20 个槽位。若 K=30 能把正确 term 放回列表,
则 domain prune 的全部测得优势只是检索深度不足的假象。

## 结果

| K | slots | 701 on-list | 701 recall | 1249 on-list | 1249 recall | delta |
|---|---|---|---|---|---|---|
| 10 | 7 | 159 | 94.6% | 159 | 94.6% | +0 |
| 20 | 14 | 163 | 97.0% | 161 | 95.8% | **-2** |
| 30 | 21 | 164 | 97.6% | 162 | 96.4% | **-2** |
| 40 | 28 | 165 | 98.2% | 163 | 97.0% | **-2** |
| 60 | 42 | 165 | 98.2% | 164 | 97.6% | -1 |

SDY1293 `microscopy assay`:

| K | 701 | 1249 |
|---|---|---|
| 20 | yes (#8) | **no** |
| 30 | yes (#8) | **yes (#18)** |
| 40/60 | yes (#8) | yes (#18) |

## 判读

**窄假设成立,宽假设证伪。** K=30 确实把 SDY1293 的 `OBI:0002119` 放回了列表(#18),
但 1249 同时**新丢一条**,净差额在 K=20/30/40 上恒为 -2,K=60 仍为 -1。
反向(1249 命中而 701 丢失)在任何 K 上都是 **0 条**。

逐条差异:

| K | 1249 丢失的 entry | curator term | 该 term 在 701 的排名 |
|---|---|---|---|
| 20 | 20078211_SDY1293 `microscopy assay` | OBI:0002119 microscopy assay | #8 |
| 20 | 32717743_SDY1655 `cytometric bead array assay` | OBI:0003115 antigen detection by CBA | #8 |
| 30 | 24336226_SDY1260 `cytometric bead array assay` | OBI:0003116 antibody detection by CBA | #19 |
| 30 | 32717743_SDY1655 `cytometric bead array assay` | OBI:0003115 antigen detection by CBA | #14 |

损失不是分散的,**集中在 cytometric bead array 族**:1249 里的 decoy 在每个深度上都把
`OBI:0003115` / `OBI:0003116` 这类精确 term 挤出去。这与"加深检索即可解决"相矛盾 ——
decoy 的排名高于目标 term,不是排在目标 term 之后。

## 对阶段二的影响

recall@K 是 exact 的**上限**,不是实际得分。上限对比:

| 臂 | 检索上限 | 实际 exact(已跑) |
|---|---|---|
| 701 @ K=20(现行) | 163 | **141** |
| 701 @ K=30 | 164 | 未跑 |
| 1249 @ K=20 | 161 | 140 |
| **1249 @ K=30** | **162** | 待测 |

1249 @ K=30 的上限(162)低于 701 @ K=20 的上限(163),所以**先验上不看好它超过 141**。
但上限远非约束(141 vs 163,中间有 22 条是 term 在列表上而 picker 选错),
所以实测仍有意义。判据沿用:benchmark 噪声为 2 条,exact ≥ 143 才算真正超过现行方案。
