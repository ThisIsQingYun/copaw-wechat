from __future__ import annotations

import asyncio
import logging
from os import getenv
from typing import Any

from wecom.constants import (
    CHANNEL_NAME,
    DEFAULT_WEBSOCKET_URL,
    ENV_BOT_ID,
    ENV_BOT_SECRET,
    ENV_CALLBACK_TOKEN,
    ENV_ENCODING_AES_KEY,
    ENV_RECEIVE_ID,
    ENV_WEBSOCKET_URL,
)
from wecom.active_reply import ResponseUrlReplyClient
from wecom.channel_service import WeComChannelService
from wecom.config import WeComConfig
from wecom.crypto import decrypt_media_bytes
from wecom.media_store import WeComMediaStore
from wecom.models import ChatType, DeliveryMode, InboundEnvelope, OutboundMessage
from wecom.runtime_compat import MissingRuntimeDependency, load_copaw_symbols
from wecom.webhook import WeComWebhookHandler
from wecom.ws.client import WeComWebSocketClient
from wecom.ws.transport import resolve_transport_factory

logger = logging.getLogger(__name__)


try:
    _symbols = load_copaw_symbols()
    BaseChannel = _symbols['BaseChannel']
    ContentType = _symbols['ContentType']
    TextContent = _symbols['TextContent']
    ImageContent = _symbols['ImageContent']
    AudioContent = _symbols['AudioContent']
    FileContent = _symbols['FileContent']
except MissingRuntimeDependency:
    BaseChannel = object
    ContentType = None
    TextContent = None
    ImageContent = None
    AudioContent = None
    FileContent = None


class WeComChannel(BaseChannel):
    channel = CHANNEL_NAME

    def __init__(
        self,
        process: Any = None,
        config: WeComConfig | None = None,
        on_reply_sent=None,
        show_tool_details: bool = True,
    ):
        self.process = process
        self.config = config or WeComConfig.from_mapping({'bot_id': '', 'secret': ''})
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
        self.service = WeComChannelService(config=self.config)
        self._media_store = WeComMediaStore(
            media_dir=self.config.media_dir,
            fetch_func=self.config.media_fetch_func,
        )
        self._enqueue = None
        self._ws_client: WeComWebSocketClient | None = None
        self._receive_task: asyncio.Task | None = None
        self._response_client = ResponseUrlReplyClient(
            post_func=self.config.response_post_func,
            timeout_seconds=self.config.response_timeout_seconds,
        )
        self._webhook_handler = None
        if self.config.token and self.config.encoding_aes_key:
            self._webhook_handler = WeComWebhookHandler(
                token=self.config.token,
                encoding_aes_key=self.config.encoding_aes_key,
                receive_id=self.config.receive_id,
            )

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
            config=WeComConfig.from_mapping(data),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
        )

    @classmethod
    def from_env(cls, process, on_reply_sent=None):
        return cls(
            process=process,
            config=WeComConfig.from_mapping({
                'bot_id': getenv(ENV_BOT_ID, ''),
                'secret': getenv(ENV_BOT_SECRET, ''),
                'token': getenv(ENV_CALLBACK_TOKEN, ''),
                'encoding_aes_key': getenv(ENV_ENCODING_AES_KEY, ''),
                'receive_id': getenv(ENV_RECEIVE_ID, ''),
                'websocket_url': getenv(ENV_WEBSOCKET_URL, DEFAULT_WEBSOCKET_URL),
            }),
            on_reply_sent=on_reply_sent,
        )

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
            content_parts.append(TextContent(type=ContentType.TEXT, text=f"[wecom_event]{payload['event']['eventtype']}"))

        for attachment in payload.get('attachments') or []:
            attachment_type = str(attachment.get('type') or '').lower()
            if attachment_type == 'image' and ImageContent is not None:
                image_url = attachment.get('local_uri') or attachment.get('url')
                if image_url:
                    content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=image_url))
            elif attachment_type == 'voice' and AudioContent is not None:
                data = attachment.get('content') or attachment.get('url') or ''
                content_parts.append(AudioContent(type=ContentType.AUDIO, data=data))
            elif attachment_type == 'file' and FileContent is not None:
                file_url = attachment.get('local_uri') or attachment.get('url')
                if file_url:
                    content_parts.append(FileContent(type=ContentType.FILE, file_url=file_url))
            elif attachment_type == 'mixed':
                for item in attachment.get('msg_item') or []:
                    item_type = str(item.get('msgtype') or '').lower()
                    if item_type == 'text':
                        item_text = (item.get('text') or {}).get('content') or ''
                        if item_text:
                            content_parts.append(TextContent(type=ContentType.TEXT, text=item_text))
                    elif item_type == 'image' and ImageContent is not None:
                        image_payload = item.get('image') or {}
                        item_url = image_payload.get('local_uri') or image_payload.get('url') or ''
                        if item_url:
                            content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=item_url))
                    elif item_type == 'file' and FileContent is not None:
                        file_payload = item.get('file') or {}
                        item_url = file_payload.get('local_uri') or file_payload.get('url') or ''
                        if item_url:
                            content_parts.append(FileContent(type=ContentType.FILE, file_url=item_url))
            elif attachment_type == 'stream':
                stream_text = attachment.get('content') or ''
                if stream_text:
                    content_parts.append(TextContent(type=ContentType.TEXT, text=stream_text))

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

    async def start(self):
        if self._ws_client is None:
            self._ws_client = WeComWebSocketClient(
                config=self.config,
                transport_factory=self._get_transport_factory(),
            )
            await self._ws_client.connect()
            if self.config.auto_receive_background and self._enqueue is not None and self._receive_task is None:
                self._receive_task = asyncio.create_task(self.run_forever(), name='wecom-channel-run-forever')
        return None

    async def run_forever(self):
        if self._ws_client is None:
            self._ws_client = WeComWebSocketClient(config=self.config, transport_factory=self._get_transport_factory())
        await self._ws_client.run_forever(self._handle_envelope)

    async def _handle_envelope(self, envelope: InboundEnvelope):
        payload = self.service.build_enqueue_payload(envelope)
        payload = await self._media_store.persist_payload(payload)
        if self._enqueue is not None:
            self._enqueue(payload)
        return payload

    async def pump_once(self):
        if self._ws_client is None:
            raise RuntimeError('WebSocket client has not been started')
        envelope = await self._ws_client.receive_one()
        return await self._handle_envelope(envelope)

    async def stop(self):
        if self._receive_task is not None:
            self._receive_task.cancel()
            await asyncio.gather(self._receive_task, return_exceptions=True)
            self._receive_task = None
        if self._ws_client is not None:
            await self._ws_client.stop()
        return None

    def handle_webhook_verification(self, query: dict[str, Any]) -> str:
        if self._webhook_handler is None:
            raise RuntimeError('Webhook crypto is not configured for this channel')
        return self._webhook_handler.handle_url_verification(query)

    async def handle_webhook_callback_async(self, query: dict[str, Any], body: dict[str, Any]) -> dict:
        if self._webhook_handler is None:
            raise RuntimeError('Webhook crypto is not configured for this channel')
        decrypted = self._webhook_handler.decrypt_callback(query=query, body=body)
        envelope = InboundEnvelope.from_dict({'cmd': 'webhook_callback', 'headers': {}, 'body': decrypted})
        return await self._handle_envelope(envelope)

    def handle_webhook_callback(self, query: dict[str, Any], body: dict[str, Any]) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.handle_webhook_callback_async(query, body))
        raise RuntimeError('handle_webhook_callback cannot be used inside a running event loop; call handle_webhook_callback_async instead')

    def encrypt_webhook_reply(self, reply_body: dict[str, Any], *, timestamp: str, nonce: str) -> dict[str, str]:
        if self._webhook_handler is None:
            raise RuntimeError('Webhook crypto is not configured for this channel')
        return self._webhook_handler.encrypt_reply(reply_body, timestamp=timestamp, nonce=nonce)

    def decrypt_media(self, encrypted_bytes: bytes, aes_key: str | None = None) -> bytes:
        key = aes_key or self.config.encoding_aes_key
        if not key:
            raise RuntimeError('No AES key configured for media decryption')
        return decrypt_media_bytes(encrypted_bytes, key)

    def _build_outbound_message(self, text: str, meta: dict[str, Any]) -> OutboundMessage:
        msgtype = str(meta.get('msgtype') or ('template_card' if meta.get('template_card') else 'markdown'))

        if msgtype == 'template_card':
            template_card = self._build_template_card(meta)
            payload = {'template_card': template_card}
            if meta.get('userids'):
                payload['userids'] = meta['userids']
        elif msgtype == 'stream':
            payload = {'stream': self._build_stream_payload(text, meta, include_feedback=True)}
        elif msgtype == 'stream_with_template_card':
            payload = {
                'stream': self._build_stream_payload(text, meta, include_feedback=True),
                'template_card': self._build_template_card(meta, fallback_feedback_key='template_card_feedback_id'),
            }
        elif msgtype == 'text':
            payload = {'text': {'content': text}}
        else:
            payload = {'markdown': {'content': text}}
            if meta.get('feedback_id'):
                payload['markdown']['feedback'] = {'id': meta['feedback_id']}

        delivery_mode = str(meta.get('delivery_mode') or '')
        if delivery_mode == 'welcome':
            mode = DeliveryMode.WELCOME
        elif delivery_mode == 'update':
            mode = DeliveryMode.UPDATE
        elif meta.get('req_id'):
            mode = DeliveryMode.RESPOND
        else:
            mode = DeliveryMode.SEND
        return OutboundMessage(msgtype=msgtype, payload=payload, mode=mode)

    async def _run_process_loop(self, request, to_handle: str, send_meta: dict[str, Any]) -> None:
        process = getattr(self, '_process', None) or getattr(self, 'process', None)
        if process is None:
            raise RuntimeError('No process handler configured for WeComChannel')

        last_response = None
        stream_states: dict[str, dict[str, Any]] = {}
        try:
            async for event in process(request):
                obj = getattr(event, 'object', None)
                if obj == 'content':
                    await self._handle_stream_content_event(to_handle, event, send_meta, stream_states)
                elif obj == 'message':
                    await self._handle_stream_message_event(to_handle, event, send_meta, stream_states)
                elif obj == 'response':
                    last_response = event
                    on_event_response = getattr(self, 'on_event_response', None)
                    if on_event_response is not None:
                        await on_event_response(request, event)

            get_error = getattr(self, '_get_response_error_message', None)
            err_msg = get_error(last_response) if callable(get_error) else None
            if err_msg:
                await self._handle_consume_error(request, to_handle, f'Error: {err_msg}')

            on_reply_sent = getattr(self, '_on_reply_sent', None) or getattr(self, 'on_reply_sent', None)
            if on_reply_sent:
                args_getter = getattr(self, 'get_on_reply_sent_args', None)
                if callable(args_getter):
                    args = args_getter(request, to_handle)
                else:
                    args = (getattr(request, 'user_id', '') or '', getattr(request, 'session_id', '') or '')
                on_reply_sent(self.channel, *args)
        except Exception:
            logger.exception('wecom channel process loop failed')
            await self._handle_consume_error(
                request,
                to_handle,
                'An error occurred while processing your request.',
            )

    async def _handle_stream_content_event(
        self,
        to_handle: str,
        event: Any,
        send_meta: dict[str, Any],
        stream_states: dict[str, dict[str, Any]],
    ) -> None:
        chunk = self._extract_stream_text_from_content(event, stream_states)
        if chunk:
            await self._send_stream_chunk(to_handle, chunk, send_meta, stream_states, event)

    async def _handle_stream_message_event(
        self,
        to_handle: str,
        event: Any,
        send_meta: dict[str, Any],
        stream_states: dict[str, dict[str, Any]],
    ) -> None:
        chunk = self._extract_stream_text_from_message(event, stream_states)
        if chunk:
            await self._send_stream_chunk(to_handle, chunk, send_meta, stream_states, event)

        if str(getattr(event, 'status', '') or '') != 'completed':
            return

        parts = self._extract_message_parts(event)
        if not parts:
            return

        state = self._get_stream_state(event, stream_states)
        if state.get('started'):
            parts = [
                part
                for part in parts
                if str(getattr(part, 'type', '') or '') not in ('text', 'refusal')
            ]
            if not parts:
                return

        await self.send_content_parts(to_handle, parts, send_meta)

    def _extract_stream_text_from_content(
        self,
        event: Any,
        stream_states: dict[str, dict[str, Any]],
    ) -> str:
        status = str(getattr(event, 'status', '') or '')
        if status not in ('in_progress', 'completed'):
            return ''

        content_type = str(getattr(event, 'type', '') or '')
        if content_type not in ('text', 'refusal'):
            return ''

        state = self._get_stream_state(event, stream_states)
        text = self._get_text_like_value(event)
        if not text:
            return ''

        if bool(getattr(event, 'delta', False)):
            state['sent_text'] += text
            return text

        return self._diff_stream_text(text, state)

    def _extract_stream_text_from_message(
        self,
        event: Any,
        stream_states: dict[str, dict[str, Any]],
    ) -> str:
        status = str(getattr(event, 'status', '') or '')
        if status not in ('in_progress', 'completed'):
            return ''

        state = self._get_stream_state(event, stream_states)
        content = list(getattr(event, 'content', None) or [])
        has_delta = any(bool(getattr(item, 'delta', False)) for item in content)

        if has_delta:
            delta_text = ''.join(
                self._get_text_like_value(item)
                for item in content
                if bool(getattr(item, 'delta', False))
            )
            if delta_text:
                state['sent_text'] += delta_text
            return delta_text

        if status == 'completed' and not state.get('started'):
            return ''

        full_text = ''.join(self._get_text_like_value(item) for item in content)
        if not full_text:
            return ''
        return self._diff_stream_text(full_text, state)

    async def _send_stream_chunk(
        self,
        to_handle: str,
        text: str,
        send_meta: dict[str, Any],
        stream_states: dict[str, dict[str, Any]],
        event: Any,
    ) -> None:
        if not text:
            return

        state = self._get_stream_state(event, stream_states)
        stream_meta = dict(send_meta or {})
        prefix = stream_meta.get('bot_prefix') or getattr(self, 'bot_prefix', '') or ''
        chunk = text
        if prefix and not state.get('prefix_sent'):
            chunk = prefix + chunk
            state['prefix_sent'] = True

        if stream_meta.get('template_card') and not state.get('template_card_sent'):
            stream_meta['msgtype'] = 'stream_with_template_card'
            state['template_card_sent'] = True
        else:
            stream_meta['msgtype'] = 'stream'

        logger.debug(
            'wecom stream chunk send: msgtype=%s chunk_len=%s preview=%s',
            stream_meta.get('msgtype'),
            len(chunk),
            chunk[:120],
        )
        await self.send(to_handle, chunk, stream_meta)
        state['started'] = True

    def _extract_message_parts(self, event: Any) -> list[Any]:
        to_parts = getattr(self, '_message_to_content_parts', None)
        if callable(to_parts):
            return list(to_parts(event) or [])
        return list(getattr(event, 'content', None) or [])

    def _get_stream_state(
        self,
        event: Any,
        stream_states: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        key = str(getattr(event, 'msg_id', None) or getattr(event, 'id', None) or '__default__')
        return stream_states.setdefault(
            key,
            {
                'sent_text': '',
                'started': False,
                'prefix_sent': False,
                'template_card_sent': False,
            },
        )

    @staticmethod
    def _get_text_like_value(item: Any) -> str:
        item_type = str(getattr(item, 'type', '') or '')
        if item_type == 'text':
            return str(getattr(item, 'text', '') or '')
        if item_type == 'refusal':
            return str(getattr(item, 'refusal', '') or '')
        return ''

    @staticmethod
    def _diff_stream_text(full_text: str, state: dict[str, Any]) -> str:
        previous = str(state.get('sent_text', '') or '')
        if full_text.startswith(previous):
            delta = full_text[len(previous):]
            state['sent_text'] = full_text
            return delta
        if not state.get('started'):
            state['sent_text'] = full_text
            return full_text
        state['sent_text'] = full_text
        return ''

    async def _handle_consume_error(self, request: Any, to_handle: str, err_text: str) -> None:
        on_consume_error = getattr(self, '_on_consume_error', None)
        if on_consume_error is None:
            raise RuntimeError(err_text)
        await on_consume_error(request, to_handle, err_text)

    async def send(self, to_handle, text, meta=None):
        meta = dict(meta or {})
        message = self._build_outbound_message(text, meta)

        response_url = meta.get('response_url')
        if response_url:
            if message.msgtype == 'template_card':
                return await self._response_client.send_template_card(str(response_url), message.payload['template_card'])
            if message.msgtype == 'markdown':
                feedback = ((message.payload.get('markdown') or {}).get('feedback') or {}).get('id')
                return await self._response_client.send_markdown(str(response_url), message.payload['markdown']['content'], feedback_id=feedback)
            return await self._response_client.send_message(str(response_url), message)

        if message.mode in (DeliveryMode.RESPOND, DeliveryMode.WELCOME, DeliveryMode.UPDATE):
            command = self.service.build_command(req_id=str(meta['req_id']), message=message)
        else:
            chat_type = ChatType.from_value(str(meta.get('chat_type', 'single')))
            req_id = str(meta.get('send_req_id') or f'send-{to_handle}')
            command = self.service.build_command(
                req_id=req_id,
                chat_id=str(to_handle),
                chat_type=chat_type,
                message=message,
            )

        if self._ws_client is not None:
            await self._ws_client.send_command(command)
        return command

    def _build_template_card(self, meta: dict[str, Any], *, fallback_feedback_key: str = 'template_card_feedback_id') -> dict[str, Any]:
        template_card = dict(meta.get('template_card') or {})
        feedback_id = meta.get(fallback_feedback_key) or meta.get('feedback_id')
        if feedback_id and not ((template_card.get('feedback') or {}).get('id')):
            template_card['feedback'] = {'id': feedback_id}
        return template_card

    def _build_stream_payload(self, text: str, meta: dict[str, Any], *, include_feedback: bool) -> dict[str, Any]:
        stream = dict(meta.get('stream') or {})
        if text and 'content' not in stream:
            stream['content'] = text
        if include_feedback:
            feedback_id = meta.get('stream_feedback_id') or meta.get('feedback_id')
            if feedback_id and not ((stream.get('feedback') or {}).get('id')):
                stream['feedback'] = {'id': feedback_id}
        return stream

    def _get_transport_factory(self):
        return resolve_transport_factory(self.config)



