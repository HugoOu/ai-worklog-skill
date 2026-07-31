"""
聚类距离阈值调优工具。

用途
----
给定一份对话导出文件（任意已注册 adapter 支持的格式），重建"聚类前"的细粒度
候选（一天一候选，未跨天合并），在其上扫描 AgglomerativeClustering 的
distance_threshold，为每个阈值报告客观指标（簇数 / 单例簇 / 最大簇 / 轮廓系数）
与簇构成预览，供人工最终裁决阈值。

方法学要点
----------
1. 轮廓系数（silhouette）只用于**划定搜索范围**，不能单独定阈值。
   在语义连续的数据上，轮廓系数的数学最优解往往是"合成一个巨簇 + 甩离群点"
   的退化解（分数最高、语义全废）。最终阈值必须由簇构成的人工语义核验敲定。
2. 调优用的 Map 候选缓存写入独立目录 output/tune_cache/，不污染生产 .map_cache。
   缓存命中条件沿用 clustering.PROMPT_VERSION（模型/prompt 变更会使其失效）。

用法
----
    .venv/Scripts/python.exe scripts/tune_cluster_threshold.py examples/ai_history.html
    .venv/Scripts/python.exe scripts/tune_cluster_threshold.py examples/ai_history.html -p google
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# 允许从项目任意位置运行本脚本：把项目根目录加入 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import typer
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_distances

from src.cache import MapCacheStore
from src.clustering import PROMPT_VERSION
from src.embedding import embed_texts, EMBEDDING_MODEL
from src.extractor import extract_candidates_from_daily, MODEL_NAME, MAX_TOKENS
from src.models import (
    CandidateItem, CandidateTopic, DayMapCache, MapRunMeta, DailyConversation,
)

TUNE_CACHE_DIR = Path("./output/tune_cache")

app = typer.Typer(add_completion=False, help="聚类距离阈值调优工具")


def _map_to_fine_candidates(
    daily_conversations: list[DailyConversation],
    cache_store: MapCacheStore,
) -> list[CandidateItem]:
    """对每天跑 Map（带缓存），返回聚类前的细粒度候选（一天一候选，未跨天合并）。"""
    items: list[CandidateItem] = []
    hits = misses = 0
    for dc in daily_conversations:
        cached = cache_store.get(dc, prompt_version=PROMPT_VERSION)
        if cached is None:
            start = datetime.now()
            candidates = extract_candidates_from_daily(dc, log=lambda *_: None)
            dur_ms = int((datetime.now() - start).total_seconds() * 1000)
            cached = DayMapCache(
                cache_key=dc.content_hash,
                date=dc.date,
                input_message_count=len(dc.messages),
                map_run=MapRunMeta(
                    run_id=os.urandom(16).hex(),
                    model=MODEL_NAME,
                    temperature=0.0,
                    max_tokens=MAX_TOKENS,
                    prompt_version=PROMPT_VERSION,
                    created_at=datetime.now().astimezone().isoformat(),
                    duration_ms=dur_ms,
                ),
                candidates=[
                    CandidateTopic(
                        topic=c.topic, summary=c.summary, evidence=c.evidence,
                        date=dc.date, session_ids=c.session_ids,
                    )
                    for c in candidates
                ],
            )
            cache_store.put(dc, cached)
            misses += 1
        else:
            hits += 1
        for ct in cached.candidates:
            items.append(CandidateItem(
                topic=ct.topic, summary=ct.summary, evidence=ct.evidence,
                dates=[dc.date], session_ids=ct.session_ids,
            ))
    print(f"Map: {hits} 天命中缓存，{misses} 天新调 LLM（prompt_version={PROMPT_VERSION}, model={MODEL_NAME}）")
    items.sort(key=lambda c: (c.dates[0], c.topic))
    return items


def _cluster_at(dist: np.ndarray, threshold: float) -> np.ndarray:
    return AgglomerativeClustering(
        n_clusters=None, distance_threshold=threshold,
        metric="precomputed", linkage="average",
    ).fit_predict(dist)


def _print_clusters(cands: list[CandidateItem], labels: np.ndarray, threshold: float, max_items: int = 8):
    clusters: dict[int, list[CandidateItem]] = defaultdict(list)
    for idx, lab in enumerate(labels):
        clusters[int(lab)].append(cands[idx])
    print(f"\n=== threshold={threshold:.2f} | 簇数={len(clusters)} 簇构成 ===")
    for lab in sorted(clusters, key=lambda l: -len(clusters[l])):
        grp = clusters[lab]
        print(f"[{len(grp)}项] " + " / ".join(c.topic for c in grp[:max_items])
              + (f" ... 另{len(grp) - max_items}项" if len(grp) > max_items else ""))


@app.command()
def main(
    input_file: Path = typer.Argument(..., exists=True, help="对话导出文件（ChatGPT/Gemini 等）"),
    provider: str = typer.Option("auto", "-p", "--provider", help="适配器：auto/openai/google"),
    lo: float = typer.Option(0.20, help="扫描下界"),
    hi: float = typer.Option(0.70, help="扫描上界"),
    step: float = typer.Option(0.02, help="扫描步长"),
    preview: list[float] = typer.Option(None, "--preview", help="额外打印簇构成的阈值（可重复）"),
):
    from src.pipeline import run
    from src.bridge import unified_to_daily

    print(f"解析 {input_file}（provider={provider}）...")
    sessions = run(input_file, provider=provider)
    daily = unified_to_daily(sessions)
    print(f"会话 {len(sessions)} → 按天归集 {len(daily)} 天，消息 {sum(len(d.messages) for d in daily)} 条")

    cache_store = MapCacheStore(TUNE_CACHE_DIR)
    cands = _map_to_fine_candidates(daily, cache_store)
    print(f"细粒度候选数: {len(cands)}")
    if len(cands) <= 1:
        print("候选过少，无法调优。")
        raise typer.Exit(1)

    print(f"Embedding model: {EMBEDDING_MODEL}")
    emb = embed_texts([f"{c.topic}。{c.summary}" for c in cands])
    dist = cosine_distances(emb)

    upper = dist[np.triu_indices_from(dist, k=1)]
    print(f"\n成对余弦距离分布: min={upper.min():.3f} p25={np.percentile(upper,25):.3f} "
          f"median={np.percentile(upper,50):.3f} p75={np.percentile(upper,75):.3f} max={upper.max():.3f}")

    print("\n" + "=" * 72)
    print(f"{'threshold':>9} | {'簇数':>4} | {'单例簇':>5} | {'最大簇':>5} | {'轮廓系数':>9}")
    print("-" * 72)
    rows = []
    th = lo
    while th <= hi + 1e-9:
        labels = _cluster_at(dist, th)
        counts = Counter(labels)
        n = len(counts)
        singletons = sum(1 for v in counts.values() if v == 1)
        largest = max(counts.values())
        if 2 <= n < len(labels):
            try:
                sil = silhouette_score(dist, labels, metric="precomputed")
            except Exception:
                sil = float("nan")
        else:
            sil = float("nan")
        rows.append((th, n, singletons, largest, sil))
        print(f"{th:>9.2f} | {n:>4} | {singletons:>5} | {largest:>5} | "
              f"{(f'{sil:+.4f}' if not np.isnan(sil) else '   n/a  '):>9}")
        th += step

    valid = [r for r in rows if not np.isnan(r[4])]
    if valid:
        best = max(valid, key=lambda r: r[4])
        print("=" * 72)
        print(f"轮廓系数最高: threshold={best[0]:.2f} (sil={best[4]:+.4f}, 簇={best[1]}, 单例={best[2]}, 最大簇={best[3]})")
        print("⚠️ 高阈值常为退化解（一个巨簇+离群点）。请结合下方簇构成人工核验后再定阈值。")

    for pv in (preview or []):
        _print_clusters(cands, _cluster_at(dist, pv), pv)


if __name__ == "__main__":
    app()