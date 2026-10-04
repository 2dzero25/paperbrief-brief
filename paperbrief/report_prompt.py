"""The text the model sees when writing a 보고서. Prompt rules are the only guard (no code check on numbers).

#9 adds the 그림 후보 selection and #10 the 재현 체크 rules here, together with the `Report` field they add.
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
"""


def build_input(body: str, figures: list[FigureCandidate]) -> str:
    """The paper text first (a stable prefix); #9 appends the 그림 후보 after it."""
    return f"<paper>\n{body}\n</paper>"
