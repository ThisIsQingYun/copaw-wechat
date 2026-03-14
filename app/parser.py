from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from .constants import APP_CHANNEL_NAME


_COMMON_KEYS = {
    'ToUserName',
    'FromUserName',
    'CreateTime',
    'MsgType',
    'MsgId',
    'AgentID',
}


def parse_plaintext_xml(xml_text: str) -> dict[str, str]:
    root = ET.fromstring(xml_text)
    payload: dict[str, str] = {}
    for child in root:
        payload[child.tag] = child.text or ''
    return payload


def build_native_payload_from_callback(
    parsed: dict[str, str],
    *,
    channel_name: str = APP_CHANNEL_NAME,
    req_id: str = '',
) -> dict[str, Any]:
    msgtype = str(parsed.get('MsgType', '')).strip().lower()
    meta = {
        'req_id': req_id,
        'msgid': str(parsed.get('MsgId', '')),
        'agent_id': str(parsed.get('AgentID', '')),
        'create_time': str(parsed.get('CreateTime', '')),
        'msgtype': msgtype,
        'chat_id': str(parsed.get('ChatId', '')),
        'raw_body': dict(parsed),
    }

    payload = {
        'channel_id': channel_name,
        'sender_id': str(parsed.get('FromUserName', '')),
        'text': '',
        'attachments': [],
        'meta': meta,
    }

    if msgtype == 'event':
        eventtype = str(parsed.get('Event', '')).strip().lower()
        event_data = {
            key: value
            for key, value in parsed.items()
            if key not in _COMMON_KEYS | {'Event'}
        }
        payload['event'] = {
            'eventtype': eventtype,
            'data': event_data,
        }
        return payload

    if msgtype == 'text':
        payload['text'] = str(parsed.get('Content', ''))
        return payload

    if msgtype == 'image':
        payload['attachments'].append(
            {
                'type': 'image',
                'media_id': str(parsed.get('MediaId', '')),
                'pic_url': str(parsed.get('PicUrl', '')),
            }
        )
        return payload

    if msgtype == 'voice':
        payload['text'] = str(parsed.get('Recognition', ''))
        payload['attachments'].append(
            {
                'type': 'voice',
                'media_id': str(parsed.get('MediaId', '')),
                'format': str(parsed.get('Format', '')),
                'recognition': str(parsed.get('Recognition', '')),
            }
        )
        return payload

    if msgtype == 'video':
        payload['attachments'].append(
            {
                'type': 'video',
                'media_id': str(parsed.get('MediaId', '')),
                'thumb_media_id': str(parsed.get('ThumbMediaId', '')),
            }
        )
        return payload

    if msgtype == 'file':
        payload['attachments'].append(
            {
                'type': 'file',
                'media_id': str(parsed.get('MediaId', '')),
                'file_name': str(parsed.get('FileName', '')),
            }
        )
        return payload

    if msgtype == 'location':
        label = str(parsed.get('Label', ''))
        location_x = str(parsed.get('Location_X', ''))
        location_y = str(parsed.get('Location_Y', ''))
        payload['text'] = f'[location] {label} ({location_x},{location_y})'.strip()
        return payload

    if msgtype == 'link':
        title = str(parsed.get('Title', ''))
        description = str(parsed.get('Description', ''))
        url = str(parsed.get('Url', ''))
        payload['text'] = '\n'.join(part for part in (title, description, url) if part)
        return payload

    payload['text'] = str(parsed.get('Content', ''))
    return payload
