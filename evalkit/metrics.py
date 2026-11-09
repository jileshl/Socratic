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

