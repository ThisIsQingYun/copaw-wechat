from __future__ import annotations

from wecom.models import ChatType, OutboundMessage


def build_response_url_body(message: OutboundMessage) -> dict:
    body = {'msgtype': message.msgtype}
    body.update(message.payload)
    return body


def build_respond_command(*, req_id: str, message: OutboundMessage) -> dict:
    return {
        'cmd': 'aibot_respond_msg',
        'headers': {'req_id': req_id},
        'body': build_response_url_body(message),
    }


def build_welcome_command(*, req_id: str, message: OutboundMessage) -> dict:
    return {
        'cmd': 'aibot_respond_welcome_msg',
        'headers': {'req_id': req_id},
        'body': build_response_url_body(message),
    }


def build_passive_update_body(*, template_card: dict, userids: list[str] | None = None) -> dict:
    body = {
        'response_type': 'update_template_card',
        'template_card': template_card,
    }
    if userids:
        body['userids'] = userids
    return body


def build_update_command(*, req_id: str, template_card: dict, userids: list[str] | None = None) -> dict:
    return {
        'cmd': 'aibot_respond_update_msg',
        'headers': {'req_id': req_id},
        'body': build_passive_update_body(template_card=template_card, userids=userids),
    }


def build_send_command(*, req_id: str, chat_id: str, chat_type: ChatType, message: OutboundMessage) -> dict:
    body = {
        'chatid': chat_id,
        'chat_type': 1 if chat_type is ChatType.SINGLE else 2,
        'msgtype': message.msgtype,
    }
    body.update(message.payload)
    return {
        'cmd': 'aibot_send_msg',
        'headers': {'req_id': req_id},
        'body': body,
    }
