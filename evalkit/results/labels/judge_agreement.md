# Judge agreement with human labels

Judge model: `google/gemini-3.1-flash-lite`. Rubric: the teacher's three dimensions, 1–5.

| Dimension | Labelled items | Exact agreement | Within 1 point | Weighted kappa | Use judge? |
|---|---|---|---|---|---|
| conceptual_accuracy | 20 | 25% | 75% | 0.42 | no: report from human labels |
| identified_misconception | 20 | 35% | 60% | 0.48 | no: report from human labels |
| socratic_guidance | 20 | 25% | 80% | -0.09 | no: report from human labels |

Labellers: Anurag Singh.
