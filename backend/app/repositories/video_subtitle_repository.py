from typing import Any, Dict, List

from beanie.odm.fields import PydanticObjectId

from app.models.content.video_subtitles import VideoSubtitle
from app.models.content.videos import Video
from app.repositories.base_repository import BaseRepository


class VideoSubtitleRepository(BaseRepository[VideoSubtitle]):
    """Repository for VideoSubtitle document operations."""

    def __init__(self) -> None:
        super().__init__(VideoSubtitle)

    async def get_many(
        self,
        filters: Dict[str, Any],
        limit: int = 100,
        skip: int = 0,
    ) -> List[VideoSubtitle]:
        """
        When filters include topic_id, resolve via Video (subtitles use video_id only).
        Otherwise delegate to a plain Beanie find.
        """
        topic_id = filters.get("topic_id")
        organization_id = filters.get("organization_id")
        extra = {
            k: v
            for k, v in filters.items()
            if k not in ("topic_id", "organization_id")
        }
        if topic_id is not None and organization_id is not None and not extra:
            videos = await Video.find(
                {"organization_id": organization_id, "topic_id": topic_id}
            ).to_list()
            if not videos:
                return []
            video_ids = [v.id for v in videos]
            q = self.model.find(
                {
                    "organization_id": organization_id,
                    "video_id": {"$in": video_ids},
                }
            ).sort([("chunk_index", 1)])
            if skip:
                q = q.skip(skip)
            return await q.limit(limit).to_list()
        return await self.model.find(filters).skip(skip).limit(limit).to_list()


def get_video_subtitle_repository() -> VideoSubtitleRepository:
    return VideoSubtitleRepository()
