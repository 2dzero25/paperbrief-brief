"""The text the model sees when writing a 보고서. Prompt rules are the only guard (no code check on numbers).

#9 added the 그림 후보 selection; #10 adds the 재현 체크 rules here, together with the `Report` field it adds.
"""
from paperbrief.parser import FigureCandidate

INSTRUCTIONS = """\
You write a report on one research paper for a reader who wants to know what the paper did before reproducing it.

Rules:
- Write in Korean. Keep technical terms, model names, dataset names and method names in their English original.
- Use only what the paper text says. If the paper does not state something, write exactly "명시 없음" for that part.
- Never write a number that does not appear in the paper text. Copy numbers as the paper gives them.
- hook: exactly one sentence that contains one key number from the paper's main result.
- method: what the paper did and how. results: the main results with their numbers.
- difference: how it differs from prior work, as the paper states it. meaning: why the result matters, as the paper argues it.
- limitations: limitations the paper admits. If it lists none, write "명시 없음".
- figures: the ids of 1-2 candidates from <figure_candidates> that show the paper's main idea or main result best, most important first. You see only each candidate's caption and the sentences that cite it, not the image. Use only ids from the list; if the list is empty, return an empty list.
- repro: five items (code, weights, data, gpu, license), each with a verdict and evidence.
  Judge ONLY from what this paper itself wrote or released. Ignore the code, weights, data and GPU of other works
  that the paper cites or surveys. Never treat a code repository registered on Hugging Face as evidence.
  verdict "공개": the paper says it released the item; evidence is where (URL, page, table number).
  verdict "비공개": the paper says it is not released or will be released later; evidence is where it says so.
  verdict "명시 없음": the paper does not mention the item; evidence is "명시 없음".
  For gpu and license with verdict "공개", evidence is the paper's original wording (for example "8×A100, 3일", "Apache-2.0").
"""


def build_input(body: str, figures: list[FigureCandidate]) -> str:
    """The paper text first (a stable prefix), then the 그림 후보: id, caption, citing sentences. Never the image."""
    return f"<paper>\n{body}\n</paper>\n{_candidates(figures)}"


def _candidates(figures: list[FigureCandidate]) -> str:
    if not figures:
        return "<figure_candidates>(none)</figure_candidates>"
    lines = []
    for f in figures:
        lines.append(f"{f.id}: {f.caption}")
        lines += [f"  cited: {m}" for m in f.mentions]
    return "<figure_candidates>\n" + "\n".join(lines) + "\n</figure_candidates>"
