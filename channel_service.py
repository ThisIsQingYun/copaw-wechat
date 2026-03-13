from __future__ import annotations

from wecom.config import WeComConfig
from wecom.models import ChatType, DeliveryMode, InboundEnvelope, OutboundMessage, ParsedMessage
from wecom.parsers.inbound import parse_inbound_envelope
from wecom.parsers.outbound import (
    build_passive_update_body,
    build_respond_command,
    build_response_url_body,
    build_send_command,
    build_update_command,
    build_welcome_command,
)


class WeComChannelService:
    def __init__(self, *, config: WeComConfig):
        self._config = config

    def build_enqueue_payload(self, envelope: InboundEnvelope) -> dict:
        parsed = parse_inbound_envelope(envelope)

        if isinstance(parsed, ParsedMessage):
            meta = {
                'req_id': parsed.req_id,
                'msgid': parsed.msgid,
                'aibotid': parsed.aibotid,
                'chat_id': parsed.chat_id,
                'chat_type': parsed.chat_type.value,
                'response_url': parsed.response_url,
                'msgtype': parsed.msgtype,
                'raw_body': parsed.raw_body,
            }
            if 'quote' in parsed.payload:
                meta['quote'] = parsed.payload['quote']

            text = ''
            if 'text' in parsed.payload:
                text = str((parsed.payload.get('text') or {}).get('content', ''))

            attachments = []
            for key in ('image', 'voice', 'file', 'mixed', 'stream'):
                if key in parsed.payload:
                    attachments.append({'type': key, **dict(parsed.payload[key])})

            return {
                'channel_id': self._config.channel_name,
                'sender_id': parsed.from_userid,
                'text': text,
                'attachments': attachments,
                'meta': meta,
            }

        meta = {
            'req_id': parsed.req_id,
            'msgid': parsed.msgid,
            'aibotid': parsed.aibotid,
            'chat_id': parsed.chat_id,
            'chat_type': parsed.chat_type.value,
            'response_url': parsed.response_url,
            'eventtype': parsed.eventtype,
            'raw_body': parsed.raw_body,
        }
        return {
            'channel_id': self._config.channel_name,
            'sender_id': parsed.from_userid,
            'text': '',
            'event': {
                'eventtype': parsed.eventtype,
                'data': parsed.event_data,
            },
            'meta': meta,
        }

    def build_command(
        self,
        *,
        req_id: str,
        message: OutboundMessage,
        chat_id: str | None = None,
        chat_type: ChatType | None = None,
    ) -> dict:
        if message.mode is DeliveryMode.RESPOND:
            return build_respond_command(req_id=req_id, message=message)
        if message.mode is DeliveryMode.WELCOME:
            return build_welcome_command(req_id=req_id, message=message)
        if message.mode is DeliveryMode.UPDATE:
            return build_update_command(
                req_id=req_id,
                template_card=message.payload['template_card'],
                userids=message.payload.get('userids'),
            )
        if message.mode is DeliveryMode.SEND:
            if chat_id is None or chat_type is None:
                raise ValueError('chat_id and chat_type are required for proactive send mode')
            return build_send_command(req_id=req_id, chat_id=chat_id, chat_type=chat_type, message=message)
        raise ValueError(f'Unsupported delivery mode: {message.mode}')

    def build_response_url_body(self, message: OutboundMessage) -> dict:
        return build_response_url_body(message)

    def build_passive_update_body(self, *, template_card: dict, userids: list[str] | None = None) -> dict:
        return build_passive_update_body(template_card=template_card, userids=userids)
