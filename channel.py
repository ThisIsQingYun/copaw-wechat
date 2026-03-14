from __future__ import annotations

import asyncio
import logging
from os import getenv
from types import SimpleNamespace
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

logger = logging.getLogger('copaw.app.channels.wecom.channel')


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
        logger.info(
            'wecom channel starting: enabled=%s websocket_url=%s auto_receive_background=%s has_enqueue=%s',
            self.enabled,
            self.config.websocket_url,
            self.config.auto_receive_background,
            self._enqueue is not None,
        )
        if self._ws_client is None:
            self._ws_client = WeComWebSocketClient(
                config=self.config,
                transport_factory=self._get_transport_factory(),
            )
            await self._ws_client.connect()
            logger.info('wecom websocket connected: bot_id=%s', (self.config.bot_id or '')[:12])
            if self.config.auto_receive_background and self._enqueue is not None and self._receive_task is None:
                self._receive_task = asyncio.create_task(self.run_forever(), name='wecom-channel-run-forever')
                logger.info('wecom background receive loop started')
            else:
                logger.warning(
                    'wecom background receive loop not started: auto_receive_background=%s has_enqueue=%s receive_task_exists=%s',
                    self.config.auto_receive_background,
                    self._enqueue is not None,
                    self._receive_task is not None,
                )
        return None

    async def run_forever(self):
        if self._ws_client is None:
            self._ws_client = WeComWebSocketClient(config=self.config, transport_factory=self._get_transport_factory())
        logger.info('wecom receive loop entering run_forever')
        await self._ws_client.run_forever(self._handle_envelope)

    async def _handle_envelope(self, envelope: InboundEnvelope):
        if envelope.is_heartbeat():
            logger.debug('wecom heartbeat received: req_id=%s', envelope.req_id)
            return None

        body = envelope.body or {}
        event = body.get('event') or {}
        body_keys = ','.join(sorted(str(key) for key in body.keys())) or '-'
        logger.info(
            'wecom inbound envelope: cmd=%s req_id=%s msgtype=%s eventtype=%s chatid=%s msgid=%s body_keys=%s has_response_url=%s errcode=%s errmsg=%s',
            envelope.cmd,
            envelope.req_id,
            body.get('msgtype', ''),
            event.get('eventtype', ''),
            body.get('chatid', ''),
            body.get('msgid', ''),
            body_keys,
            bool(body.get('response_url')),
            body.get('errcode', ''),
            body.get('errmsg', ''),
        )
        payload = self.service.build_enqueue_payload(envelope)
        payload = await self._media_store.persist_payload(payload)
        if self._enqueue is not None:
            self._enqueue(payload)
        return payload

    async def pump_once(self):
        if self._ws_client is None:
            raise RuntimeError('WebSocket client has not been started')
        envelope = await self._ws_client.receive_dispatchable()
        return await self._handle_envelope(envelope)

    async def stop(self):
        logger.info('wecom channel stopping')
        if self._receive_task is not None:
            self._receive_task.cancel()
            await asyncio.gather(self._receive_task, return_exceptions=True)
            self._receive_task = None
        if self._ws_client is not None:
            await self._ws_client.stop()
        logger.info('wecom channel stopped')
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
        delivery_state = {'sent': False}
        try:
            async for event in process(request):
                obj = getattr(event, 'object', None)
                logger.debug(
                    'wecom process event: object=%s status=%s type=%s',
                    obj,
                    getattr(event, 'status', None),
                    getattr(event, 'type', ''),
                )
                if obj == 'content':
                    await self._handle_stream_content_event(
                        to_handle,
                        event,
                        send_meta,
                        stream_states,
                        delivery_state,
                    )
                elif obj == 'message':
                    await self._handle_stream_message_event(
                        to_handle,
                        event,
                        send_meta,
                        stream_states,
                        delivery_state,
                    )
                elif obj == 'response':
                    last_response = event
                    on_event_response = getattr(self, 'on_event_response', None)
                    if on_event_response is not None:
                        await on_event_response(request, event)

            get_error = getattr(self, '_get_response_error_message', None)
            err_msg = get_error(last_response) if callable(get_error) else None
            if err_msg:
                await self._handle_consume_error(request, to_handle, f'Error: {err_msg}')
            else:
                await self._send_final_response_output_if_needed(
                    last_response,
                    to_handle,
                    send_meta,
                    delivery_state,
                    stream_states,
                )

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
        delivery_state: dict[str, bool],
    ) -> None:
        state, changed = self._update_stream_state_from_content(event, stream_states)
        status = str(getattr(event, 'status', '') or '')
        self._log_stream_state_update('content', event, state, changed)
        if status == 'completed':
            if changed:
                await self._send_stream_snapshot(
                    to_handle,
                    send_meta,
                    stream_states,
                    delivery_state,
                    event,
                    finish=False,
                )
            return
        if changed:
            await self._send_stream_snapshot(
                to_handle,
                send_meta,
                stream_states,
                delivery_state,
                event,
                finish=False,
            )

    async def _handle_stream_message_event(
        self,
        to_handle: str,
        event: Any,
        send_meta: dict[str, Any],
        stream_states: dict[str, dict[str, Any]],
        delivery_state: dict[str, bool],
    ) -> None:
        state, changed = self._update_stream_state_from_message(event, stream_states)
        status = str(getattr(event, 'status', '') or '')
        stream_target_state = state
        stream_target_event = event
        stream_text_sent = False
        self._log_stream_state_update('message', event, state, changed)

        if status == 'completed':
            stream_target_state, stream_target_event = self._resolve_completion_stream_target(
                event,
                state,
                stream_states,
            )
            if stream_target_state is not state:
                logger.debug(
                    'wecom stream completion handoff: source_state=%s target_state=%s target_len=%s',
                    state.get('state_key', ''),
                    stream_target_state.get('state_key', ''),
                    len(str(stream_target_state.get('current_text', '') or '')),
                )
            if stream_target_state.get('started') or changed:
                await self._send_stream_snapshot(
                    to_handle,
                    send_meta,
                    stream_states,
                    delivery_state,
                    stream_target_event,
                    finish=True,
                )
                stream_text_sent = True
        elif changed:
            await self._send_stream_snapshot(
                to_handle,
                send_meta,
                stream_states,
                delivery_state,
                event,
                finish=False,
            )

        if status != 'completed':
            return

        parts = self._extract_message_parts(event)
        if not parts:
            return

        if stream_text_sent or stream_target_state.get('started'):
            parts = [
                part
                for part in parts
                if str(self._read_item_field(part, 'type', '') or '') not in ('text', 'refusal')
            ]
            if not parts:
                return

        await self.send_content_parts(to_handle, parts, send_meta)
        delivery_state['sent'] = True

    def _update_stream_state_from_content(
        self,
        event: Any,
        stream_states: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        status = str(getattr(event, 'status', '') or '')
        state = self._get_stream_state(event, stream_states)
        if status not in ('in_progress', 'completed'):
            return state, False

        content_type = str(getattr(event, 'type', '') or '')
        if content_type not in ('text', 'refusal'):
            return state, False

        text = self._get_text_like_value(event)
        if not text:
            return state, False

        current_text = str(state.get('current_text', '') or '')
        if bool(getattr(event, 'delta', False)):
            next_text = current_text + text
        else:
            next_text = text

        changed = next_text != current_text
        state['current_text'] = next_text
        return state, changed

    def _update_stream_state_from_message(
        self,
        event: Any,
        stream_states: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        status = str(getattr(event, 'status', '') or '')
        state = self._get_stream_state(event, stream_states)
        if status not in ('in_progress', 'completed'):
            return state, False

        content = list(getattr(event, 'content', None) or [])
        current_text = str(state.get('current_text', '') or '')
        has_delta = any(bool(getattr(item, 'delta', False)) for item in content)

        if has_delta:
            delta_text = ''.join(
                self._get_text_like_value(item)
                for item in content
                if bool(getattr(item, 'delta', False))
            )
            if not delta_text:
                return state, False
            next_text = current_text + delta_text
        else:
            next_text = ''.join(self._get_text_like_value(item) for item in content)
            if not next_text:
                return state, False

        changed = next_text != current_text
        state['current_text'] = next_text
        return state, changed

    async def _send_stream_snapshot(
        self,
        to_handle: str,
        send_meta: dict[str, Any],
        stream_states: dict[str, dict[str, Any]],
        delivery_state: dict[str, bool],
        event: Any,
        *,
        finish: bool,
    ) -> None:
        state = self._get_stream_state(event, stream_states)
        base_text = str(state.get('current_text', '') or '')
        if not base_text:
            return

        stream_meta = dict(send_meta or {})
        prefix = stream_meta.get('bot_prefix') or getattr(self, 'bot_prefix', '') or ''
        display_text = f'{prefix}{base_text}' if prefix else base_text

        if display_text == state.get('last_sent_text') and finish == bool(state.get('last_sent_finish', False)):
            return

        stream_payload = dict(stream_meta.get('stream') or {})
        stream_payload['id'] = self._resolve_stream_id(event, stream_states, stream_payload, send_meta)
        stream_payload['content'] = display_text
        stream_payload['finish'] = finish
        stream_meta['stream'] = stream_payload

        if stream_meta.get('template_card') and not state.get('template_card_sent'):
            stream_meta['msgtype'] = 'stream_with_template_card'
            state['template_card_sent'] = True
        else:
            stream_meta['msgtype'] = 'stream'

        logger.debug(
            'wecom stream snapshot send: source=%s status=%s state_key=%s msgtype=%s stream_id=%s finish=%s content_len=%s preview=%s',
            getattr(event, 'object', 'state'),
            getattr(event, 'status', ''),
            state.get('state_key', ''),
            stream_meta.get('msgtype'),
            stream_payload.get('id', ''),
            finish,
            len(display_text),
            self._preview_text(display_text),
        )
        await self.send(to_handle, display_text, stream_meta)
        state['started'] = True
        state['last_sent_text'] = display_text
        state['last_sent_finish'] = finish
        delivery_state['sent'] = True

    def _resolve_stream_id(
        self,
        event: Any,
        stream_states: dict[str, dict[str, Any]],
        stream_payload: dict[str, Any],
        send_meta: dict[str, Any],
    ) -> str:
        state = self._get_stream_state(event, stream_states)
        configured_id = str(stream_payload.get('id') or '')
        if configured_id:
            state['stream_id'] = configured_id
            return configured_id

        existing_id = str(state.get('stream_id', '') or '')
        if existing_id:
            return existing_id

        request_key = str((send_meta or {}).get('req_id') or 'request')
        state_key = str(state.get('state_key', '') or '__default__')
        generated_id = f'wecom-stream-{request_key}-{state_key}'
        state['stream_id'] = generated_id
        return generated_id

    def _extract_message_parts(self, event: Any) -> list[Any]:
        if isinstance(event, dict):
            return list(event.get('content') or [])
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
                'state_key': key,
                'current_text': '',
                'started': False,
                'template_card_sent': False,
                'last_sent_text': '',
                'last_sent_finish': False,
                'stream_id': '',
            },
        )

    def _resolve_completion_stream_target(
        self,
        event: Any,
        state: dict[str, Any],
        stream_states: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], Any]:
        if state.get('started'):
            return state, event

        started_states = [item for item in stream_states.values() if item.get('started')]
        if len(started_states) != 1:
            return state, event

        target_state = started_states[0]
        next_text = str(state.get('current_text', '') or '')
        if next_text:
            target_state['current_text'] = next_text
        return target_state, SimpleNamespace(id=target_state.get('state_key', '__default__'))

    @staticmethod
    def _preview_text(text: Any, *, limit: int = 120) -> str:
        normalized = str(text or '').replace('\r', '\\r').replace('\n', '\\n')
        if len(normalized) <= limit:
            return normalized
        return f'{normalized[:limit]}...'

    def _log_stream_state_update(
        self,
        source: str,
        event: Any,
        state: dict[str, Any],
        changed: bool,
    ) -> None:
        current_text = str(state.get('current_text', '') or '')
        logger.debug(
            'wecom stream state update: source=%s status=%s state_key=%s changed=%s started=%s current_len=%s delta=%s preview=%s',
            source,
            getattr(event, 'status', ''),
            state.get('state_key', ''),
            changed,
            bool(state.get('started')),
            len(current_text),
            bool(getattr(event, 'delta', False)),
            self._preview_text(current_text),
        )

    def _log_response_completion_state(
        self,
        reason: str,
        last_response: Any,
        delivery_state: dict[str, bool],
        stream_states: dict[str, dict[str, Any]],
        *,
        output_count: int,
    ) -> None:
        started = [state['state_key'] for state in stream_states.values() if state.get('started')]
        unfinished = [
            state['state_key']
            for state in stream_states.values()
            if state.get('started') and not state.get('last_sent_finish')
        ]
        logger.info(
            'wecom response completion state: reason=%s status=%s output_count=%s started=%s unfinished=%s sent=%s',
            reason,
            getattr(last_response, 'status', None),
            output_count,
            started,
            unfinished,
            bool(delivery_state.get('sent')),
        )

    @staticmethod
    def _read_item_field(item: Any, field: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(field, default)
        return getattr(item, field, default)

    @classmethod
    def _get_text_like_value(cls, item: Any) -> str:
        item_type = str(cls._read_item_field(item, 'type', '') or '')
        if item_type == 'text':
            return str(cls._read_item_field(item, 'text', '') or '')
        if item_type == 'refusal':
            return str(cls._read_item_field(item, 'refusal', '') or '')
        return ''


    async def _send_final_response_output_if_needed(
        self,
        last_response: Any,
        to_handle: str,
        send_meta: dict[str, Any],
        delivery_state: dict[str, bool],
        stream_states: dict[str, dict[str, Any]],
    ) -> None:
        if not last_response:
            self._log_response_completion_state(
                'no_response',
                last_response,
                delivery_state,
                stream_states,
                output_count=0,
            )
            await self._finish_started_streams_if_needed(
                to_handle,
                send_meta,
                delivery_state,
                stream_states,
            )
            return

        output = list(getattr(last_response, 'output', None) or [])
        if not output:
            self._log_response_completion_state(
                'empty_output',
                last_response,
                delivery_state,
                stream_states,
                output_count=0,
            )
            await self._finish_started_streams_if_needed(
                to_handle,
                send_meta,
                delivery_state,
                stream_states,
            )
            return

        final_message = output[-1]
        parts = self._extract_message_parts(final_message)
        if not parts:
            self._log_response_completion_state(
                'empty_final_parts',
                last_response,
                delivery_state,
                stream_states,
                output_count=len(output),
            )
            await self._finish_started_streams_if_needed(
                to_handle,
                send_meta,
                delivery_state,
                stream_states,
            )
            return

        self._log_response_completion_state(
            'final_output',
            last_response,
            delivery_state,
            stream_states,
            output_count=len(output),
        )

        if await self._finalize_stream_from_response_output(
            final_message,
            to_handle,
            send_meta,
            delivery_state,
            stream_states,
        ):
            return

        if delivery_state.get('sent'):
            return

        logger.info('wecom final response fallback send: parts_count=%s', len(parts))
        await self.send_content_parts(to_handle, parts, send_meta)
        delivery_state['sent'] = True

    async def _finish_started_streams_if_needed(
        self,
        to_handle: str,
        send_meta: dict[str, Any],
        delivery_state: dict[str, bool],
        stream_states: dict[str, dict[str, Any]],
    ) -> bool:
        started_state_keys = [
            state['state_key']
            for state in stream_states.values()
            if state.get('started') and state.get('current_text') and not state.get('last_sent_finish')
        ]
        if not started_state_keys:
            return False

        logger.debug('wecom response completion closing open streams: state_keys=%s', started_state_keys)
        for state_key in started_state_keys:
            await self._send_stream_snapshot(
                to_handle,
                send_meta,
                stream_states,
                delivery_state,
                SimpleNamespace(id=state_key),
                finish=True,
            )
        return True

    async def _finalize_stream_from_response_output(
        self,
        final_message: Any,
        to_handle: str,
        send_meta: dict[str, Any],
        delivery_state: dict[str, bool],
        stream_states: dict[str, dict[str, Any]],
    ) -> bool:
        started_state_keys = [
            state['state_key']
            for state in stream_states.values()
            if state.get('started')
        ]
        if not started_state_keys:
            return False

        parts = self._extract_message_parts(final_message)
        text_parts = []
        non_text_parts = []
        for part in parts:
            part_type = str(self._read_item_field(part, 'type', '') or '')
            if part_type in ('text', 'refusal'):
                text_parts.append(part)
            else:
                non_text_parts.append(part)

        final_text = ''.join(self._get_text_like_value(part) for part in text_parts)
        if not final_text and not non_text_parts:
            return False

        if final_text:
            for state_key in started_state_keys:
                state = stream_states.get(state_key) or {}
                state['current_text'] = final_text
                await self._send_stream_snapshot(
                    to_handle,
                    send_meta,
                    stream_states,
                    delivery_state,
                    SimpleNamespace(id=state_key),
                    finish=True,
                )

        if non_text_parts:
            await self.send_content_parts(to_handle, non_text_parts, send_meta)
            delivery_state['sent'] = True

        return bool(final_text or non_text_parts)

    async def _handle_consume_error(self, request: Any, to_handle: str, err_text: str) -> None:
        on_consume_error = getattr(self, '_on_consume_error', None)
        if on_consume_error is None:
            raise RuntimeError(err_text)
        await on_consume_error(request, to_handle, err_text)
    async def send(self, to_handle, text, meta=None):
        meta = dict(meta or {})
        message = self._build_outbound_message(text, meta)

        response_url = meta.get('response_url')
        send_log = logger.debug if message.msgtype in ('stream', 'stream_with_template_card') else logger.info
        send_log(
            'wecom outbound send: msgtype=%s mode=%s to_handle=%s has_response_url=%s text_len=%s',
            message.msgtype,
            getattr(message.mode, 'value', message.mode),
            str(to_handle)[:64],
            bool(response_url),
            len(text or ''),
        )
        if message.msgtype in ('stream', 'stream_with_template_card'):
            stream_payload = dict(message.payload.get('stream') or {})
            logger.debug(
                'wecom outbound stream payload: stream_id=%s finish=%s content_len=%s preview=%s',
                stream_payload.get('id', ''),
                bool(stream_payload.get('finish')),
                len(str(stream_payload.get('content', '') or '')),
                self._preview_text(stream_payload.get('content', '')),
            )

        if message.mode in (DeliveryMode.RESPOND, DeliveryMode.WELCOME, DeliveryMode.UPDATE):
            command = self.service.build_command(req_id=str(meta['req_id']), message=message)
            if self._ws_client is not None:
                command_log = logger.debug if message.msgtype in ('stream', 'stream_with_template_card') else logger.info
                command_log(
                    'wecom outbound command sent via websocket: cmd=%s req_id=%s',
                    command.get('cmd'),
                    (command.get('headers') or {}).get('req_id', ''),
                )
                await self._ws_client.send_command(command)
                return command
            if response_url:
                logger.info('wecom outbound reply falling back to response_url: req_id=%s', str(meta.get('req_id', '')))
                if message.msgtype == 'template_card':
                    return await self._response_client.send_template_card(str(response_url), message.payload['template_card'])
                if message.msgtype == 'markdown':
                    feedback = ((message.payload.get('markdown') or {}).get('feedback') or {}).get('id')
                    return await self._response_client.send_markdown(str(response_url), message.payload['markdown']['content'], feedback_id=feedback)
                return await self._response_client.send_message(str(response_url), message)
            logger.warning(
                'wecom outbound command not sent: websocket client is not connected and response_url is missing (cmd=%s req_id=%s)',
                command.get('cmd'),
                (command.get('headers') or {}).get('req_id', ''),
            )
            return command

        chat_type = ChatType.from_value(str(meta.get('chat_type', 'single')))
        req_id = str(meta.get('send_req_id') or f'send-{to_handle}')
        command = self.service.build_command(
            req_id=req_id,
            chat_id=str(to_handle),
            chat_type=chat_type,
            message=message,
        )

        if self._ws_client is not None:
            logger.info(
                'wecom outbound proactive command sent via websocket: cmd=%s req_id=%s',
                command.get('cmd'),
                (command.get('headers') or {}).get('req_id', ''),
            )
            await self._ws_client.send_command(command)
            return command

        logger.warning(
            'wecom outbound command not sent: websocket client is not connected and response_url is missing (cmd=%s req_id=%s)',
            command.get('cmd'),
            (command.get('headers') or {}).get('req_id', ''),
        )
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














