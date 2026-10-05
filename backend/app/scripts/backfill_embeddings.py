"""
Backfill precomputed embeddings for TopicNote and TopicQuestionBank (MongoDB).

Run from the `backend` directory:
  python -m app.scripts.backfill_embeddings

Uses MONGODB_URL from app settings (see app.core.config.Settings).
"""

from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.core.database import connect_to_mongo
from app.models.content.topic_notes import TopicNote
from app.models.content.topic_question_bank import TopicQuestionBank
from app.services.embedding_service import get_embedding


async def run() -> None:
    notes = await TopicNote.find({}).to_list()
    for note in notes:
        if note.embedding is None:
            text = f"{note.concept or ''} {note.content_markdown or ''}".strip()
            if text:
                note.embedding = get_embedding(text[:1000])
                await note.save()

    questions = await TopicQuestionBank.find({}).to_list()
    for q in questions:
        if q.embedding is None:
            text = f"{q.concept or ''} {q.question_text or ''}".strip()
            if text:
                q.embedding = get_embedding(text[:1000])
                await q.save()


async def main() -> None:
    settings = Settings()
    await connect_to_mongo(mongodb_url=settings.MONGODB_URL)
    await run()


if __name__ == "__main__":
    asyncio.run(main())
