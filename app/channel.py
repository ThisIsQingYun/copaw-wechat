from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from os import getenv
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

from wecom.runtime_compat import MissingRuntimeDependency, load_copaw_symbols

from .api_client import WeComAppApiClient
from .callback import WeComAppCallbackHandler
from .config import WeComAppConfig
from .constants import (
    APP_CHANNEL_NAME,
    ENV_APP_AGENT_ID,
    ENV_APP_CALLBACK_HOST,
    ENV_APP_CALLBACK_PATH,
    ENV_APP_CALLBACK_PORT,
    ENV_APP_CALLBACK_TOKEN,
    ENV_APP_CORP_ID,
    ENV_APP_EGRESS_PROXY_URL,
    ENV_APP_ENCODING_AES_KEY,
    ENV_APP_RECEIVE_ID,
    ENV_APP_SECRET,
)
from .media_store import WeComAppMediaStore
from .parser import build_native_payload_from_callback, parse_plaintext_xml
from .server import WeComAppCallbackServer

logger = logging.getLogger('copaw.app.channels.wecom.app.channel')


try:
    _symbols = load_copaw_symbols()
    BaseChannel = _symbols['BaseChannel']
    ContentType = _symbols['ContentType']
    TextContent = _symbols['TextContent']
    ImageContent = _symbols['ImageContent']
    AudioContent = _symbols['AudioContent']
    VideoContent = _symbols['VideoContent']
    FileContent = _symbols['FileContent']
except MissingRuntimeDependency:
    BaseChannel = object
    ContentType = None
    TextContent = None
    ImageContent = None
    AudioContent = None
    VideoContent = None
    FileContent = None


class WeComAppChannel(BaseChannel):
    channel = APP_CHANNEL_NAME

    def __init__(
        self,
        process: Any = None,
        config: WeComAppConfig | None = None,
        on_reply_sent=None,
        show_tool_details: bool = True,
    ):
        self.process = process
        self.config = config or WeComAppConfig.from_mapping({})
        if BaseChannel is not object:
            super().__init__(
                process,
                on_reply_sent=on_reply_sent,
                show_tool_details=show_tool_details,
                filter_tool_messages=self.config.filter_tool_messages,
                filter_thinking=self.config.filter_thinking,
                dm_policy=self.config.dm_policy,
                group_policy=self.config.group_policy,
                allow_from=self.config.allow_from,
                deny_message=self.config.deny_message,
                require_mention=self.config.require_mention,
            )
        self.enabled = self.config.enabled
        self.bot_prefix = self.config.bot_prefix
        self.on_reply_sent = on_reply_sent
        self._enqueue = None
        self._api_client = WeComAppApiClient(self.config)
        self._media_store = WeComAppMediaStore(self.config.media_dir)
        self._callback_handler = None
        if self.config.token and self.config.encoding_aes_key:
            self._callback_handler = WeComAppCallbackHandler(
                token=self.config.token,
                encoding_aes_key=self.config.encoding_aes_key,
                receive_id=self.config.receive_id,
            )
        self._callback_server: WeComAppCallbackServer | None = None

    @classmethod
    def from_config(
        cls,
        process,
        config,
        on_reply_sent=None,
        show_tool_details=True,
        filter_tool_messages=False,
        filter_thinking=False,
    ):
        data = dict(config) if isinstance(config, dict) else dict(getattr(config, '__dict__', {}))
        data.setdefault('enabled', getattr(config, 'enabled', True))
        data.setdefault('bot_prefix', getattr(config, 'bot_prefix', ''))
        data.setdefault('filter_tool_messages', getattr(config, 'filter_tool_messages', filter_tool_messages))
        data.setdefault('filter_thinking', getattr(config, 'filter_thinking', filter_thinking))
        data.setdefault('dm_policy', getattr(config, 'dm_policy', 'open'))
        data.setdefault('group_policy', getattr(config, 'group_policy', 'open'))
        data.setdefault('allow_from', getattr(config, 'allow_from', []))
        data.setdefault('deny_message', getattr(config, 'deny_message', ''))
        data.setdefault('require_mention', getattr(config, 'require_mention', False))
        return cls(
            process=process,
            config=WeComAppConfig.from_mapping(data),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
        )

    @classmethod
    def from_env(cls, process, on_reply_sent=None):
        return cls(
            process=process,
            config=WeComAppConfig.from_mapping(
                {
                    'corp_id': getenv(ENV_APP_CORP_ID, ''),
                    'agent_secret': getenv(ENV_APP_SECRET, ''),
                    'agent_id': getenv(ENV_APP_AGENT_ID, ''),
                    'token': getenv(ENV_APP_CALLBACK_TOKEN, ''),
                    'encoding_aes_key': getenv(ENV_APP_ENCODING_AES_KEY, ''),
                    'receive_id': getenv(ENV_APP_RECEIVE_ID, ''),
                    'callback_host': getenv(ENV_APP_CALLBACK_HOST, ''),
                    'callback_port': getenv(ENV_APP_CALLBACK_PORT, ''),
                    'callback_path': getenv(ENV_APP_CALLBACK_PATH, ''),
                    'egress_proxy_url': getenv(ENV_APP_EGRESS_PROXY_URL, ''),
                }
            ),
            on_reply_sent=on_reply_sent,
        )

    async def start(self):
        logger.info(
            'wecom_app channel starting: enabled=%s callback=%s:%s%s auto_start=%s',
            self.enabled,
            self.config.callback_host,
            self.config.callback_port,
            self.config.callback_path,
            self.config.auto_start_callback_server,
        )
        if not self.config.auto_start_callback_server:
            return None
        if self._callback_handler is None:
            logger.warning('wecom_app callback server not started: token or encoding_aes_key is missing')
            return None
        if self._callback_server is None:
            self._callback_server = WeComAppCallbackServer(
                host=self.config.callback_host,
                port=self.config.callback_port,
                path=self.config.callback_path,
                on_verify=self.handle_callback_verification,
                on_callback=self.handle_callback_post_async,
            )
            await self._callback_server.start()
            logger.info('wecom_app callback server started')
        return None

    async def stop(self):
        logger.info('wecom_app channel stopping')
        if self._callback_server is not None:
            await self._callback_server.stop()
            self._callback_server = None
        await self._api_client.aclose()
        logger.info('wecom_app channel stopped')
        return None

    def build_agent_request_from_native(self, native_payload):
        if TextContent is None or ContentType is None:
            raise MissingRuntimeDependency(
                'copaw runtime dependencies are missing. This adapter can only build AgentRequest objects '
                'inside a real copaw runtime environment.'
            )

        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get('channel_id') or self.channel
        sender_id = payload.get('sender_id') or ''
        meta = dict(payload.get('meta') or {})
        meta['attachments'] = [dict(item) for item in payload.get('attachments') or []]
        if 'event' in payload:
            meta['event'] = payload['event']
        session_id = self.resolve_session_id(sender_id, meta)

        content_parts = []
        text = payload.get('text')
        if text:
            content_parts.append(TextContent(type=ContentType.TEXT, text=text))
        elif payload.get('event'):
            eventtype = str((payload['event'] or {}).get('eventtype', '')).strip()
            content_parts.append(TextContent(type=ContentType.TEXT, text=f'[wecom_app_event]{eventtype}'))

        for attachment in payload.get('attachments') or []:
            attachment_type = str(attachment.get('type') or '').lower()
            local_url = attachment.get('local_uri') or attachment.get('url')
            if attachment_type == 'image' and ImageContent is not None and local_url:
                content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=local_url))
            elif attachment_type == 'voice' and AudioContent is not None:
                data = attachment.get('local_uri') or attachment.get('recognition') or ''
                content_parts.append(AudioContent(type=ContentType.AUDIO, data=data))
            elif attachment_type == 'video' and VideoContent is not None and local_url:
                content_parts.append(VideoContent(type=ContentType.VIDEO, video_url=local_url))
            elif attachment_type == 'file' and FileContent is not None and local_url:
                content_parts.append(FileContent(type=ContentType.FILE, file_url=local_url))

        if not content_parts:
            content_parts.append(TextContent(type=ContentType.TEXT, text=''))

        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.channel_meta = meta
        return request

    def handle_callback_verification(self, query: dict[str, Any]) -> str:
        if self._callback_handler is None:
            raise RuntimeError('Callback crypto is not configured for this channel')
        return self._callback_handler.handle_url_verification(query)

    async def handle_callback_post_async(self, query: dict[str, Any], body_xml: str) -> str:
        if self._callback_handler is None:
            raise RuntimeError('Callback crypto is not configured for this channel')
        plaintext_xml, parsed = self._callback_handler.decrypt_callback_xml(query=query, body_xml=body_xml)
        return await self.handle_plaintext_callback_xml(
            plaintext_xml,
            parsed=parsed,
            req_id=str(query.get('msg_signature') or ''),
        )

    def handle_callback_post(self, query: dict[str, Any], body_xml: str) -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.handle_callback_post_async(query, body_xml))
        raise RuntimeError('handle_callback_post cannot be used inside a running event loop; call handle_callback_post_async instead')

    async def handle_plaintext_callback_xml(
        self,
        xml_text: str,
        *,
        parsed: dict[str, str] | None = None,
        req_id: str = '',
    ) -> str:
        parsed = parsed or parse_plaintext_xml(xml_text)
        payload = build_native_payload_from_callback(parsed, channel_name=self.channel, req_id=req_id)
        payload = await self._media_store.persist_payload(payload, self._api_client)
        if self._enqueue is not None:
            self._enqueue(payload)
        logger.info(
            'wecom_app inbound callback: msgtype=%s sender=%s msgid=%s',
            payload['meta'].get('msgtype', ''),
            payload.get('sender_id', ''),
            payload['meta'].get('msgid', ''),
        )
        return 'success'

    async def send(self, to_handle, text, meta=None):
        meta = dict(meta or {})
        msgtype = str(meta.get('msgtype') or 'text').lower()
        text_value = f'{self.bot_prefix}{text}' if self.bot_prefix and text else text

        target = self._api_client.resolve_target(str(to_handle), meta=meta)
        payload = target.apply_to_payload({})
        payload['agentid'] = self.config.agent_id
        if meta.get('enable_duplicate_check') is not None:
            payload['enable_duplicate_check'] = int(bool(meta.get('enable_duplicate_check')))
        if meta.get('duplicate_check_interval') is not None:
            payload['duplicate_check_interval'] = int(meta['duplicate_check_interval'])
        if meta.get('safe') is not None:
            payload['safe'] = int(bool(meta['safe']))

        if target.is_appchat and msgtype == 'template_card':
            raise ValueError('template_card is not supported for appchat sends')

        if msgtype == 'markdown':
            payload['msgtype'] = 'markdown'
            payload['markdown'] = {'content': text_value}
        elif msgtype == 'textcard':
            payload['msgtype'] = 'textcard'
            payload['textcard'] = dict(meta.get('textcard') or {})
            if text_value and 'description' not in payload['textcard']:
                payload['textcard']['description'] = text_value
        elif msgtype == 'news':
            payload['msgtype'] = 'news'
            payload['news'] = dict(meta.get('news') or {})
        elif msgtype == 'mpnews':
            payload['msgtype'] = 'mpnews'
            payload['mpnews'] = dict(meta.get('mpnews') or {})
        elif msgtype == 'miniprogram_notice':
            payload['msgtype'] = 'miniprogram_notice'
            payload['miniprogram_notice'] = dict(meta.get('miniprogram_notice') or {})
        elif msgtype == 'template_card':
            payload['msgtype'] = 'template_card'
            payload['template_card'] = dict(meta.get('template_card') or {})
        else:
            payload['msgtype'] = 'text'
            payload['text'] = {'content': text_value}

        if target.is_appchat:
            payload.pop('agentid', None)

        logger.info(
            'wecom_app outbound send: msgtype=%s target=%s appchat=%s',
            payload['msgtype'],
            str(to_handle)[:64],
            target.is_appchat,
        )
        return await self._api_client.send_payload(payload, use_appchat=target.is_appchat)

    async def send_media(self, to_handle, media, meta=None):
        meta = dict(meta or {})
        content, filename, content_type, message_type = await self._coerce_media_input(media, meta)
        upload_type = self._resolve_upload_type(message_type, content_type)
        upload = await self._api_client.upload_media(
            media_type=upload_type,
            content=content,
            filename=filename,
            content_type=content_type,
        )

        target = self._api_client.resolve_target(str(to_handle), meta=meta)
        payload = target.apply_to_payload({})
        if not target.is_appchat:
            payload['agentid'] = self.config.agent_id
        payload['msgtype'] = upload_type
        payload[upload_type] = {'media_id': upload['media_id']}

        logger.info(
            'wecom_app outbound media send: type=%s target=%s appchat=%s filename=%s',
            upload_type,
            str(to_handle)[:64],
            target.is_appchat,
            filename,
        )
        return await self._api_client.send_payload(payload, use_appchat=target.is_appchat)

    async def send_content_parts(self, to_handle, parts, meta=None):
        meta = dict(meta or {})
        text_parts = []
        media_parts = []
        for part in parts:
            part_type = getattr(part, 'type', None)
            if self._matches_type(part_type, 'text') and getattr(part, 'text', None):
                text_parts.append(part.text or '')
            elif self._matches_type(part_type, 'refusal') and getattr(part, 'refusal', None):
                text_parts.append(part.refusal or '')
            elif self._matches_type(part_type, 'image', 'video', 'audio', 'file'):
                media_parts.append(part)

        if text_parts:
            await self.send(to_handle, '\n'.join(text_parts), meta)
        for part in media_parts:
            await self.send_media(to_handle, part, meta)

    async def _coerce_media_input(self, media: Any, meta: dict[str, Any]) -> tuple[bytes, str, str, str]:
        message_type = str(meta.get('msgtype') or getattr(media, 'type', '') or '').lower()
        if not message_type:
            message_type = self._infer_message_type_from_media(media)

        if isinstance(media, (bytes, bytearray)):
            filename = str(meta.get('filename') or f'media{self._default_suffix(message_type)}')
            content_type = str(meta.get('content_type') or mimetypes.guess_type(filename)[0] or 'application/octet-stream')
            return bytes(media), filename, content_type, message_type

        source = (
            getattr(media, 'image_url', None)
            or getattr(media, 'video_url', None)
            or getattr(media, 'file_url', None)
            or getattr(media, 'url', None)
            or getattr(media, 'data', None)
            or meta.get('media_url')
            or meta.get('file_url')
        )
        if source is None:
            raise ValueError('Unsupported media payload: missing data source')

        if isinstance(source, bytes):
            filename = str(meta.get('filename') or f'media{self._default_suffix(message_type)}')
            content_type = str(meta.get('content_type') or mimetypes.guess_type(filename)[0] or 'application/octet-stream')
            return source, filename, content_type, message_type

        source_str = str(source)
        if source_str.startswith('file://'):
            path = Path(url2pathname(urlparse(source_str).path))
            content = path.read_bytes()
            filename = path.name
            content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            return content, filename, content_type, message_type

        if source_str.startswith('http://') or source_str.startswith('https://'):
            if callable(self.config.media_fetch_func):
                result = await self.config.media_fetch_func(source_str)
                if isinstance(result, dict):
                    return (
                        bytes(result['content']),
                        str(result.get('filename') or Path(urlparse(source_str).path).name or f'media{self._default_suffix(message_type)}'),
                        str(result.get('content_type') or 'application/octet-stream'),
                        message_type,
                    )
                if isinstance(result, (bytes, bytearray)):
                    filename = Path(urlparse(source_str).path).name or f'media{self._default_suffix(message_type)}'
                    content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
                    return bytes(result), filename, content_type, message_type

            async with httpx.AsyncClient(timeout=self.config.request_timeout_seconds) as client:
                response = await client.get(source_str)
                response.raise_for_status()
                filename = Path(urlparse(source_str).path).name or f'media{self._default_suffix(message_type)}'
                content_type = response.headers.get('content-type', '') or mimetypes.guess_type(filename)[0] or 'application/octet-stream'
                return await response.aread(), filename, content_type, message_type

        path = Path(os.path.expanduser(source_str))
        content = path.read_bytes()
        filename = path.name
        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        return content, filename, content_type, message_type

    @staticmethod
    def _infer_message_type_from_media(media: Any) -> str:
        media_type = str(getattr(media, 'type', '') or '').lower()
        if media_type in ('image', 'video', 'audio', 'file'):
            return 'voice' if media_type == 'audio' else media_type
        if getattr(media, 'image_url', None):
            return 'image'
        if getattr(media, 'video_url', None):
            return 'video'
        if getattr(media, 'file_url', None):
            return 'file'
        return 'file'

    @staticmethod
    def _resolve_upload_type(message_type: str, content_type: str) -> str:
        normalized = str(message_type or '').lower()
        if normalized in ('image', 'voice', 'video', 'file'):
            return normalized
        if content_type.startswith('image/'):
            return 'image'
        if content_type.startswith('audio/'):
            return 'voice'
        if content_type.startswith('video/'):
            return 'video'
        return 'file'

    @staticmethod
    def _default_suffix(message_type: str) -> str:
        return {
            'image': '.jpg',
            'voice': '.amr',
            'video': '.mp4',
        }.get(message_type, '.bin')

    @staticmethod
    def _matches_type(value: Any, *names: str) -> bool:
        raw = str(value or '').lower()
        for name in names:
            if raw == name or raw.endswith(f'.{name}') or raw.endswith(f'_{name}'):
                return True
        return False
