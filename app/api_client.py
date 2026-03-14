from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .config import WeComAppConfig
from .models import WeComAppSendTarget, WeComDownloadedMedia


def _ensure_success(payload: dict[str, Any]) -> dict[str, Any]:
    if int(payload.get('errcode', 0) or 0) != 0:
        raise RuntimeError(f'WeCom API error {payload.get("errcode")}: {payload.get("errmsg", "")}')
    return payload


def _filename_from_headers(headers: httpx.Headers) -> str:
    content_disposition = headers.get('content-disposition', '')
    for chunk in content_disposition.split(';'):
        chunk = chunk.strip()
        if chunk.startswith('filename='):
            return chunk.split('=', 1)[1].strip('"')
    return ''


class WeComAppApiClient:
    def __init__(self, config: WeComAppConfig):
        self.config = config
        self._request_func = config.api_request_func
        self._token = ''
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        now = time.time()
        if (
            not force_refresh
            and self._token
            and now < self._token_expires_at - max(self.config.token_refresh_skew_seconds, 0)
        ):
            return self._token

        async with self._token_lock:
            now = time.time()
            if (
                not force_refresh
                and self._token
                and now < self._token_expires_at - max(self.config.token_refresh_skew_seconds, 0)
            ):
                return self._token

            payload = await self._request_json(
                'GET',
                '/cgi-bin/gettoken',
                params={'corpid': self.config.corp_id, 'corpsecret': self.config.agent_secret},
            )
            self._token = str(payload.get('access_token', ''))
            expires_in = int(payload.get('expires_in', 7200) or 7200)
            self._token_expires_at = time.time() + expires_in
            return self._token

    async def send_text(self, to_handle: str, text: str, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        target = self.resolve_target(to_handle, meta=meta)
        payload = self._build_target_payload(target)
        payload.update(
            {
                'msgtype': 'text',
                'text': {'content': text},
            }
        )
        return await self.send_payload(payload, use_appchat=target.is_appchat)

    async def send_payload(self, payload: dict[str, Any], *, use_appchat: bool = False) -> dict[str, Any]:
        access_token = await self.get_access_token()
        endpoint = '/cgi-bin/appchat/send' if use_appchat else '/cgi-bin/message/send'
        final_payload = dict(payload)
        if not use_appchat:
            final_payload.setdefault('agentid', self.config.agent_id)
        return await self._request_json(
            'POST',
            endpoint,
            params={'access_token': access_token},
            json=final_payload,
        )

    async def update_template_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        access_token = await self.get_access_token()
        return await self._request_json(
            'POST',
            '/cgi-bin/message/update_template_card',
            params={'access_token': access_token},
            json=payload,
        )

    async def recall_message(self, msgid: str) -> dict[str, Any]:
        access_token = await self.get_access_token()
        return await self._request_json(
            'POST',
            '/cgi-bin/message/recall',
            params={'access_token': access_token},
            json={'msgid': msgid},
        )

    async def create_appchat(self, payload: dict[str, Any]) -> dict[str, Any]:
        access_token = await self.get_access_token()
        return await self._request_json(
            'POST',
            '/cgi-bin/appchat/create',
            params={'access_token': access_token},
            json=payload,
        )

    async def update_appchat(self, payload: dict[str, Any]) -> dict[str, Any]:
        access_token = await self.get_access_token()
        return await self._request_json(
            'POST',
            '/cgi-bin/appchat/update',
            params={'access_token': access_token},
            json=payload,
        )

    async def get_appchat(self, chatid: str) -> dict[str, Any]:
        access_token = await self.get_access_token()
        return await self._request_json(
            'GET',
            '/cgi-bin/appchat/get',
            params={'access_token': access_token, 'chatid': chatid},
        )

    async def upload_media(
        self,
        *,
        media_type: str,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, Any]:
        access_token = await self.get_access_token()
        return await self._request_json(
            'POST',
            '/cgi-bin/media/upload',
            params={'access_token': access_token, 'type': media_type},
            files={'media': (filename, content, content_type)},
        )

    async def download_media(self, media_id: str) -> WeComDownloadedMedia:
        access_token = await self.get_access_token()
        return await self._request_bytes(
            'GET',
            '/cgi-bin/media/get',
            params={'access_token': access_token, 'media_id': media_id},
        )

    def resolve_target(self, to_handle: str, *, meta: dict[str, Any] | None = None) -> WeComAppSendTarget:
        meta = dict(meta or {})
        if meta.get('chatid'):
            return WeComAppSendTarget(chatid=str(meta['chatid']))
        if meta.get('use_appchat'):
            return WeComAppSendTarget(chatid=str(to_handle))
        if meta.get('touser') or meta.get('toparty') or meta.get('totag'):
            return WeComAppSendTarget(
                touser=self._normalize_recipient(meta.get('touser')),
                toparty=self._normalize_recipient(meta.get('toparty')),
                totag=self._normalize_recipient(meta.get('totag')),
            )

        raw = str(to_handle or '').strip()
        lowered = raw.lower()
        if lowered.startswith('appchat:'):
            return WeComAppSendTarget(chatid=raw.split(':', 1)[1].strip())
        if lowered.startswith('party:'):
            return WeComAppSendTarget(toparty=raw.split(':', 1)[1].strip())
        if lowered.startswith('tag:'):
            return WeComAppSendTarget(totag=raw.split(':', 1)[1].strip())
        if lowered.startswith('user:'):
            raw = raw.split(':', 1)[1].strip()
        return WeComAppSendTarget(touser=self._normalize_recipient(raw))

    def _build_target_payload(self, target: WeComAppSendTarget) -> dict[str, Any]:
        return target.apply_to_payload({})

    def _api_url(self, path: str) -> str:
        return f'{self.config.api_base_url}{path}'

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.request_timeout_seconds,
                proxy=self.config.egress_proxy_url or None,
                trust_env=not bool(self.config.egress_proxy_url),
                headers={'User-Agent': 'copaw-wecom/1.0'},
            )
        return self._client

    async def _request_json(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        if self._request_func is not None:
            payload = await self._request_func(method, self._api_url(path), **kwargs)
            return _ensure_success(dict(payload))

        response = await self._get_client().request(method, self._api_url(path), **kwargs)
        response.raise_for_status()
        return _ensure_success(response.json())

    async def _request_bytes(self, method: str, path: str, **kwargs) -> WeComDownloadedMedia:
        if self._request_func is not None:
            payload = await self._request_func(method, self._api_url(path), expect='bytes', **kwargs)
            if isinstance(payload, WeComDownloadedMedia):
                return payload
            if isinstance(payload, dict) and 'content' in payload:
                return WeComDownloadedMedia(
                    content=bytes(payload['content']),
                    filename=str(payload.get('filename', '')),
                    content_type=str(payload.get('content_type', 'application/octet-stream')),
                )
            if isinstance(payload, (bytes, bytearray)):
                return WeComDownloadedMedia(
                    content=bytes(payload),
                    filename='',
                    content_type='application/octet-stream',
                )
            raise TypeError('Custom media request function must return bytes or media metadata')

        response = await self._get_client().request(method, self._api_url(path), **kwargs)
        response.raise_for_status()
        content = await response.aread()
        return WeComDownloadedMedia(
            content=content,
            filename=_filename_from_headers(response.headers),
            content_type=response.headers.get('content-type', 'application/octet-stream'),
        )

    @staticmethod
    def _normalize_recipient(value: Any) -> str:
        if isinstance(value, (list, tuple, set)):
            return '|'.join(str(item).strip() for item in value if str(item).strip())
        return str(value or '').strip()
