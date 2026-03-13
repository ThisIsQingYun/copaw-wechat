from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

import httpx

from wecom.crypto import decrypt_media_bytes


FetchFunc = Callable[[str], Any]
_IMAGE_SUFFIX_BY_SIGNATURE = (
    (b'\x89PNG\r\n\x1a\n', '.png'),
    (b'\xff\xd8\xff', '.jpg'),
    (b'GIF87a', '.gif'),
    (b'GIF89a', '.gif'),
    (b'BM', '.bmp'),
)


class WeComMediaStore:
    def __init__(
        self,
        *,
        media_dir: str = '',
        fetch_func: FetchFunc | None = None,
        timeout_seconds: int = 20,
    ):
        self._media_dir = Path(media_dir).expanduser() if media_dir else None
        self._fetch_func = fetch_func
        self._timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return self._media_dir is not None

    async def persist_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return payload

        attachments = [dict(item) for item in payload.get('attachments') or []]
        if not attachments:
            return payload

        meta = dict(payload.get('meta') or {})
        msgid = str(meta.get('msgid') or meta.get('req_id') or 'wecom-media')
        persisted = []
        for index, attachment in enumerate(attachments):
            persisted.append(await self._persist_attachment(attachment, msgid=msgid, index=index))

        updated_meta = dict(meta)
        updated_meta['attachments'] = persisted

        updated_payload = dict(payload)
        updated_payload['attachments'] = persisted
        updated_payload['meta'] = updated_meta
        return updated_payload

    async def _persist_attachment(self, attachment: dict[str, Any], *, msgid: str, index: int) -> dict[str, Any]:
        attachment_type = str(attachment.get('type') or '').lower()
        if attachment_type in ('image', 'file'):
            return await self._persist_binary_attachment(attachment, kind=attachment_type, msgid=msgid, index=index)
        if attachment_type == 'mixed':
            return await self._persist_mixed_attachment(attachment, msgid=msgid, index=index)
        return attachment

    async def _persist_mixed_attachment(self, attachment: dict[str, Any], *, msgid: str, index: int) -> dict[str, Any]:
        items = []
        for item_index, item in enumerate(attachment.get('msg_item') or []):
            item_copy = dict(item)
            item_type = str(item_copy.get('msgtype') or '').lower()
            if item_type in ('image', 'file'):
                nested = dict(item_copy.get(item_type) or {})
                nested['type'] = item_type
                nested = await self._persist_binary_attachment(
                    nested,
                    kind=item_type,
                    msgid=f'{msgid}-mixed-{index}',
                    index=item_index,
                )
                nested.pop('type', None)
                item_copy[item_type] = nested
            items.append(item_copy)
        attachment['msg_item'] = items
        return attachment

    async def _persist_binary_attachment(
        self,
        attachment: dict[str, Any],
        *,
        kind: str,
        msgid: str,
        index: int,
    ) -> dict[str, Any]:
        url = str(attachment.get('url') or '').strip()
        if not url:
            return attachment

        try:
            data = await self._fetch_bytes(url)
            aeskey = str(attachment.get('aeskey') or '').strip()
            if aeskey:
                data = decrypt_media_bytes(data, aeskey)
            target = self._build_target_path(kind=kind, msgid=msgid, index=index, url=url, data=data)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            resolved = target.resolve()
            attachment['local_path'] = str(resolved)
            attachment['local_uri'] = resolved.as_uri()
        except Exception as exc:
            attachment['download_error'] = str(exc)
        return attachment

    async def _fetch_bytes(self, url: str) -> bytes:
        if self._fetch_func is None:
            async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.content

        result = self._fetch_func(url)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, (bytes, bytearray)):
            raise TypeError('media fetch function must return bytes')
        return bytes(result)

    def _build_target_path(self, *, kind: str, msgid: str, index: int, url: str, data: bytes) -> Path:
        assert self._media_dir is not None
        suffix = self._infer_suffix(kind=kind, url=url, data=data)
        safe_msgid = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in msgid) or 'wecom-media'
        return self._media_dir / kind / f'{safe_msgid}-{index}{suffix}'

    def _infer_suffix(self, *, kind: str, url: str, data: bytes) -> str:
        parsed = Path(unquote(urlparse(url).path)).suffix.strip()
        if parsed:
            return parsed
        if kind == 'image':
            for signature, suffix in _IMAGE_SUFFIX_BY_SIGNATURE:
                if data.startswith(signature):
                    return suffix
            if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
                return '.webp'
            return '.jpg'
        return '.bin'
