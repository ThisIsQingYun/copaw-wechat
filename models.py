from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChatType(str, Enum):
    SINGLE = 'single'
    GROUP = 'group'

    @classmethod
    def from_value(cls, value: str) -> 'ChatType':
        normalized = value.strip().lower()
        return cls(normalized)


class DeliveryMode(str, Enum):
    RESPOND = 'respond'
    UPDATE = 'update'
    SEND = 'send'
    WELCOME = 'welcome'


@dataclass(slots=True)
class InboundEnvelope:
    cmd: str
    req_id: str
    body: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> 'InboundEnvelope':
        headers = payload.get('headers') or {}
        body = payload.get('body') or {}
        return cls(
            cmd=str(payload.get('cmd', '')),
            req_id=str(headers.get('req_id', '')),
            body=dict(body),
        )

    def is_heartbeat(self) -> bool:
        cmd = self.cmd.strip().lower()
        if cmd in ('ping', 'pong'):
            return True
        if not self.req_id.startswith('ping-'):
            return False
        if not self.body:
            return True
        return not any(
            self.body.get(key)
            for key in ('msgtype', 'event', 'msgid', 'chatid', 'response_url')
        )


@dataclass(slots=True)
class ParsedMessage:
    req_id: str
    msgid: str
    aibotid: str
    chat_id: str | None
    chat_type: ChatType
    from_userid: str
    response_url: str | None
    msgtype: str
    payload: dict[str, Any]
    raw_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedEvent:
    req_id: str
    msgid: str
    aibotid: str
    chat_id: str | None
    chat_type: ChatType
    from_userid: str
    from_corpid: str | None
    response_url: str | None
    eventtype: str
    event_data: dict[str, Any]
    raw_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutboundMessage:
    msgtype: str
    payload: dict[str, Any]
    mode: DeliveryMode = DeliveryMode.RESPOND
