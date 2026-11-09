"""Metrics and scoring functions for Socratic Tutor."""

from typing import Sequence


def compute_recall_at_k(retrieved_ids: list[str], gold_ids: list[str], k: int = 5) -> float:
    """Calculate Recall@K given gold cited section/passage IDs."""
    if not gold_ids:
        return 1.0
    top_k = set(retrieved_ids[:k])
    matched = sum(1 for gid in gold_ids if gid in top_k)
    return matched / len(gold_ids)


def compute_cohens_kappa(rater1: Sequence[int], rater2: Sequence[int]) -> float:
    """Compute Cohen's kappa coefficient between LLM Judge and Teacher labels."""
    if len(rater1) != len(rater2) or len(rater1) == 0:
        return 0.0
    n = len(rater1)
    agreed = sum(1 for a, b in zip(rater1, rater2) if a == b)
    p0 = agreed / n
    # Marginal probabilities
    all_categories = set(rater1).union(set(rater2))
    pe = 0.0
    for c in all_categories:
        p1_c = sum(1 for a in rater1 if a == c) / n
        p2_c = sum(1 for b in rater2 if b == c) / n
        pe += p1_c * p2_c
    if pe == 1.0:
        return 1.0
    return (p0 - pe) / (1.0 - pe)


def compute_learning_gain(pre_score: float, post_score: float) -> float:
    """Normalized learning gain g = (post - pre) / (1.0 - pre)."""
    if pre_score >= 1.0:
        return 0.0
    return max(0.0, (post_score - pre_score) / (1.0 - pre_score))


# TODO (Milestone 8 / L13): Compute Answer Leak Rate across practice runs
def compute_answer_leak_rate(leak_flags: list[bool]) -> float:
    """Fraction of practice turns where an answer or direct derivation was leaked."""
    if not leak_flags:
        return 0.0
    return sum(1 for flag in leak_flags if flag) / len(leak_flags)


# TODO (Milestone 8 / L13): Compute Misconception Diagnostic Precision & Recall
def compute_misconception_accuracy(predicted_ids: list[str], gold_ids: list[str]) -> float:
    """Accuracy of Diagnostician matching the student's seeded misconception."""
    if not gold_ids:
        return 1.0
    matched = sum(1 for pred, gold in zip(predicted_ids, gold_ids) if pred == gold)
    return matched / len(gold_ids)



def compute_weighted_kappa(rater1: Sequence[int], rater2: Sequence[int], categories: Sequence[int] = (1, 2, 3, 4, 5)) -> float:
    """Quadratic-weighted Cohen's kappa for ordinal scores (e.g. the teacher's 1-5 rubric).

    A disagreement of 1 point costs much less than a disagreement of 4 points.
    Returns 1.0 for perfect agreement and 0.0 for chance-level agreement.
    """
    if len(rater1) != len(rater2) or len(rater1) == 0:
        return 0.0
    cats = list(categories)
    index = {c: i for i, c in enumerate(cats)}
    k, n = len(cats), len(rater1)
    observed = [[0.0] * k for _ in range(k)]
    for a, b in zip(rater1, rater2):
        observed[index[a]][index[b]] += 1
    row = [sum(observed[i]) for i in range(k)]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    weight = lambda i, j: ((i - j) ** 2) / ((k - 1) ** 2)  # noqa: E731
    num = sum(weight(i, j) * observed[i][j] for i in range(k) for j in range(k))
    den = sum(weight(i, j) * row[i] * col[j] / n for i in range(k) for j in range(k))
    if den == 0:
        return 1.0
    return 1.0 - num / den
