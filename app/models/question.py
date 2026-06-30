"""Question model — reusable question representation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class QuestionKind(Enum):
    INFO = "info"
    TRUE_FALSE = "true_false"
    CHOICE = "choice"
    MULTI_CHOICE = "multi"
    ORDER = "order"
    WRITE = "write"
    FILL = "fill"


_TITLES: dict[QuestionKind, str] = {
    QuestionKind.INFO: "Read check",
    QuestionKind.TRUE_FALSE: "True or false",
    QuestionKind.CHOICE: "Select response",
    QuestionKind.MULTI_CHOICE: "Select all that apply",
    QuestionKind.ORDER: "Order correctly",
    QuestionKind.WRITE: "Write response",
    QuestionKind.FILL: "Fill the blank",
}


@dataclass
class Question:
    id: int
    question_type: QuestionKind
    question_text: str
    options: list[str] | None = None
    correct_answer: list[str] | None = None
    order_matters: bool = False
    answer_match: str = "exact"

    @property
    def title(self) -> str:
        return _TITLES[self.question_type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "question_type": self.question_type.value,
            "question_text": self.question_text,
            "options": self.options,
            "correct_answer": self.correct_answer,
            "order_matters": self.order_matters,
            "answer_match": self.answer_match,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Question:
        return cls(
            id=d["id"],
            question_type=QuestionKind(d["question_type"]),
            question_text=d["question_text"],
            options=d.get("options"),
            correct_answer=d.get("correct_answer"),
            order_matters=d.get("order_matters", False),
            answer_match=d.get("answer_match", "exact"),
        )
