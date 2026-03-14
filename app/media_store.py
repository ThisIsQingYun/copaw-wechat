from __future__ import annotations

import mimetypes
from pathlib import Path

from .api_client import WeComAppApiClient


class WeComAppMediaStore:
    def __init__(self, media_dir: str):
        self._media_dir = Path(media_dir).expanduser()

    async def persist_payload(self, payload: dict, api_client: WeComAppApiClient) -> dict:
        attachments = []
        for attachment in payload.get('attachments') or []:
            attachments.append(await self.persist_attachment(dict(attachment), api_client))
        payload['attachments'] = attachments
        return payload

    async def persist_attachment(self, attachment: dict, api_client: WeComAppApiClient) -> dict:
        media_id = str(attachment.get('media_id') or '')
        if not media_id:
            return attachment

        media = await api_client.download_media(media_id)
        suffix = self._guess_suffix(media.content_type, attachment)
        filename = str(
            attachment.get('file_name')
            or attachment.get('filename')
            or media.filename
            or f'{media_id}{suffix}'
        )
        target_dir = self._media_dir / attachment.get('type', 'file')
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        target_path.write_bytes(media.content)

        attachment['content_type'] = media.content_type
        attachment['local_path'] = str(target_path)
        attachment['local_uri'] = target_path.resolve().as_uri()
        return attachment

    @staticmethod
    def _guess_suffix(content_type: str, attachment: dict) -> str:
        guessed = mimetypes.guess_extension(content_type or '')
        if guessed:
            return guessed
        attachment_type = str(attachment.get('type') or '').lower()
        if attachment_type == 'voice':
            return '.amr'
        if attachment_type == 'video':
            return '.mp4'
        if attachment_type == 'image':
            return '.jpg'
        return '.bin'
