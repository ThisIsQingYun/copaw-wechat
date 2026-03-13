from __future__ import annotations

from typing import Any

from wecom.models import ChatType, InboundEnvelope, ParsedEvent, ParsedMessage


_MESSAGE_PAYLOAD_KEYS = ('text', 'image', 'mixed', 'voice', 'file', 'stream', 'quote')


def parse_inbound_envelope(envelope: InboundEnvelope) -> ParsedMessage | ParsedEvent:
    body = envelope.body
    msgtype = str(body.get('msgtype', ''))
    from_info = body.get('from') or {}
    chat_type = ChatType.from_value(str(body.get('chattype', 'single') or 'single'))

    if msgtype == 'event':
        event = body.get('event') or {}
        eventtype = str(event.get('eventtype', ''))
        event_data = dict(event.get(eventtype) or {})
        return ParsedEvent(
            req_id=envelope.req_id,
            msgid=str(body.get('msgid', '')),
            aibotid=str(body.get('aibotid', '')),
            chat_id=body.get('chatid'),
            chat_type=chat_type,
            from_userid=str(from_info.get('userid', '')),
            from_corpid=from_info.get('corpid'),
            response_url=body.get('response_url'),
            eventtype=eventtype,
            event_data=event_data,
            raw_body=dict(body),
        )

    payload: dict[str, Any] = {}
    for key in _MESSAGE_PAYLOAD_KEYS:
        if key in body:
            payload[key] = body[key]

    return ParsedMessage(
        req_id=envelope.req_id,
        msgid=str(body.get('msgid', '')),
        aibotid=str(body.get('aibotid', '')),
        chat_id=body.get('chatid'),
        chat_type=chat_type,
        from_userid=str(from_info.get('userid', '')),
        response_url=body.get('response_url'),
        msgtype=msgtype,
        payload=payload,
        raw_body=dict(body),
    )
