# Project 9 redesign brief

Written as a P7.3 close-out deliverable (2026-11-14). P7.3 spent the
"rerank" result: the cross-encoder reranker is a Project 7 result,
credited to P7 and never re-claimed by P9. This brief redefines
Project 9's headline around what P7.3 proved is still open.

## The spent variable

P7.2 froze retrieval as Project 9's headline variable. P7.3
unfroze it: the shipped service now reranks its dense top-25 with
a local ONNX cross-encoder (`Xenova/ms-marco-MiniLM-L-6-v2`) to a
final top-10, raising the groundable ceiling from C = 23 to
C′ = 26 and the measured S1 from 20–21 to 23–24 (A4/B4). P9 must
not re-run "add a reranker" as its headline — that experiment is
done, its numbers belong to P7, and re-claiming them would double
count one result across two projects.

## P9's new headline

**Retrieval quality versus answerability on contamination-free
papers.** P7's evaluation corpus is one famous paper the model
already knows, which contaminates every answer-level number with
model memory (proven on d02: a fact absent from the context scored
from memory in B3). P9 measures the same pipeline on papers the
model cannot know, and separates what retrieval delivers from what
the model answers.

## Design

- **Sets.** P8's frozen held-out set (96 questions, 24 post-cutoff
  papers from `evaluation/heldout/manifest.json`) plus the
  Transformer set (26 key facts, 12 questions) as the contaminated
  control.
- **Ladder, fixed top_k = 10.** Bi-encoder baseline (the P5/P6/P7
  line), then + cross-encoder rerank (P7.3 = the new baseline),
  then + hybrid sparse/dense fusion (the `tsv` column is ready),
  then + chunking variants, then optionally + query rewriting.
  Each rung changes one variable; the dense stage
  (`all-MiniLM-L6-v2`) stays constant across P5–P9, and the
  reranker is a separate, named component.
- **Metrics.** Bearing-chunk recall@10 next to regex-present
  coverage (the P7.3 design check's method: recompute the ceiling
  per rung with the frozen scorer). Headline phenomenon: the
  measured presence-vs-answerability gap — facts present in the
  context that the model still does not answer — with paired
  cluster-bootstrap intervals. RAGAS faithfulness/context metrics
  are the secondary cross-system comparison, budget-aware.

## Evidence banked from P7

- Ceiling C = 23 at frozen top-10; C′ = 26 under the P7.3
  reranker (chunk 11 → d02 position 4 in both batching modes;
  chunk 27 → d09 position 4 full-batch / 5 sub-batched).
- Bearing-chunk ranks: d02 facts at rank 11, d09 label smoothing
  at rank 18.
- The famous-paper memory confound on d02 (proven).
- Frozen-scorer phrasing losses on d03/d12; the presence-vs-
  answerability gap (P7.2: 19 of 23 groundable answered;
  P7.3: 23–24 of 26).
- The int8 reranker's scores depend on batch composition
  (sub-batching changes scores by up to 0.45 logits) — any P9
  reranker comparison must fix its batching.

## Constraints carried forward

Zero API cost; the held-out manifest is frozen; the questions and
scorer are frozen copies from Project 6; thresholds are never
silently re-registered (append-only DECISIONS entries with
daggers); original runs stay in every table.
