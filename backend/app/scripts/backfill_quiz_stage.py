"""
Inventory and backfill quiz_stage / question_type on TopicQuestionBank rows.

Untagged rows (quiz_stage is null) are ignored by structured concept-check and
cluster-quiz pickers. This script:

  1. Always infers and writes question_type when missing.
  2. Optionally assigns quiz_stage:
       - mcq / fill_in_blank → concept_check
       - descriptive → cluster_quiz

Run from `backend`:
  # Dry-run inventory (default)
  python -m app.scripts.backfill_quiz_stage

  # Apply question_type only
  python -m app.scripts.backfill_quiz_stage --apply-type

  # Apply question_type + quiz_stage heuristics
  python -m app.scripts.backfill_quiz_stage --apply-type --apply-stage

Uses MONGODB_URL from app settings.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from app.core.config import Settings
from app.core.database import connect_to_mongo
from app.models.content.topic_question_bank import TopicQuestionBank
from app.services.handlers.concept_check_question_types import infer_bank_question_type


def _stage_for_type(qtype: str) -> str:
    if qtype in ("mcq", "fill_in_blank"):
        return "concept_check"
    return "cluster_quiz"


async def run(*, apply_type: bool, apply_stage: bool) -> None:
    rows = await TopicQuestionBank.find({}).to_list()
    untagged = [q for q in rows if getattr(q, "quiz_stage", None) is None]
    missing_type = [q for q in rows if not getattr(q, "question_type", None)]

    stage_counts = Counter(getattr(q, "quiz_stage", None) or "null" for q in rows)
    type_counts = Counter(
        getattr(q, "question_type", None) or infer_bank_question_type(q) for q in rows
    )

    print(f"Total questions: {len(rows)}")
    print(f"Untagged (quiz_stage=null): {len(untagged)}")
    print(f"Missing question_type: {len(missing_type)}")
    print(f"Stage distribution: {dict(stage_counts)}")
    print(f"Type distribution (stored or inferred): {dict(type_counts)}")

    type_updated = 0
    stage_updated = 0

    for q in rows:
        changed = False
        inferred = infer_bank_question_type(q)

        if apply_type and not getattr(q, "question_type", None):
            q.question_type = inferred  # type: ignore[assignment]
            type_updated += 1
            changed = True

        effective_type = getattr(q, "question_type", None) or inferred
        if apply_stage and getattr(q, "quiz_stage", None) is None:
            q.quiz_stage = _stage_for_type(str(effective_type))  # type: ignore[assignment]
            stage_updated += 1
            changed = True

        if changed:
            await q.save()

    if apply_type or apply_stage:
        print(f"Updated question_type on {type_updated} rows")
        print(f"Updated quiz_stage on {stage_updated} rows")
    else:
        print("Dry-run only. Pass --apply-type and/or --apply-stage to write.")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill quiz_stage / question_type")
    parser.add_argument(
        "--apply-type",
        action="store_true",
        help="Write inferred question_type when missing",
    )
    parser.add_argument(
        "--apply-stage",
        action="store_true",
        help="Assign quiz_stage for null rows (mcq/fill→concept_check, else cluster_quiz)",
    )
    args = parser.parse_args()

    settings = Settings()
    await connect_to_mongo(mongodb_url=settings.MONGODB_URL)
    await run(apply_type=args.apply_type, apply_stage=args.apply_stage)


if __name__ == "__main__":
    asyncio.run(main())
