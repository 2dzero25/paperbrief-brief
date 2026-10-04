"""The text the model sees when answering a 질문. Same rules as the 보고서; prompt-only, no code check on numbers.

Order matters for prompt caching: `INSTRUCTIONS` is fixed, then the body and the report (stable per paper),
then the growing history, and the new question last.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # llm.py imports this module
    from paperbrief.llm import QA, Report

INSTRUCTIONS = """\
You answer a reader's questions about one research paper. You get the full paper text, a report written from it,
and the earlier questions and answers about this paper.

Rules:
- Answer in the same language as the question.
- Use only what the paper text says. If the paper does not state something, say "명시 없음" for that part.
- Never write a number that does not appear in the paper text. Copy numbers as the paper gives them.
- Keep technical terms, model names, dataset names and method names in their English original.
- Answer the question asked, briefly. Use the earlier questions and answers for context only.
"""


def build_input(body: str, report: "Report", history: "list[QA]", question: str) -> str:
    past = "".join(f"<q>{qa.question}</q>\n<a>{qa.answer}</a>\n" for qa in history)
    return (
        f"<paper>\n{body}\n</paper>\n<report>\n{report.model_dump_json()}\n</report>\n"
        f"<history>\n{past}</history>\n<question>\n{question}\n</question>"
    )
