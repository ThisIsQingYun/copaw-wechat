from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


_POLICY_ALIASES = {
    'open': 'open',
    'allowlist': 'allowlist',
    '开放': 'open',
    '白名单列表': 'allowlist',
}


def _normalize_policy(value: Any, *, field_name: str) -> str:
    normalized = str(value or 'open').strip().lower()
    if normalized in _POLICY_ALIASES:
        return _POLICY_ALIASES[normalized]

    raw = str(value or 'open').strip()
    if raw in _POLICY_ALIASES:
        return _POLICY_ALIASES[raw]

    allowed = ', '.join(['open', 'allowlist', '开放', '白名单列表'])
    raise ValueError(f'{field_name} must be one of: {allowed}')


@dataclass(slots=True)
class WeComConfig:
    bot_id: str
    secret: str
    channel_name: str = 'wecom'
    enabled: bool = True
    bot_prefix: str = ''
    filter_tool_messages: bool = False
    filter_thinking: bool = False
    dm_policy: str = 'open'
    group_policy: str = 'open'
    allow_from: list[str] = field(default_factory=list)
    deny_message: str = ''
    require_mention: bool = False
    media_dir: str = '~/.copaw/media/wecom'
    ping_interval_seconds: int = 20
    reconnect_delay_seconds: int = 5
    transport_factory: Any = None
    websocket_url: str = 'wss://openws.work.weixin.qq.com'
    auto_reconnect: bool = True
    auto_receive_background: bool = True
    token: str = ''
    encoding_aes_key: str = ''
    receive_id: str = ''
    response_timeout_seconds: int = 10
    response_post_func: Any = None
    media_fetch_func: Any = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> 'WeComConfig':
        bot_id = str(data['bot_id'])
        secret = str(data['secret'])
        allow_from = data.get('allow_from') or []
        if not isinstance(allow_from, list):
            allow_from = list(allow_from)
        return cls(
            bot_id=bot_id,
            secret=secret,
            channel_name=str(data.get('channel_name', 'wecom')),
            enabled=bool(data.get('enabled', True)),
            bot_prefix=str(data.get('bot_prefix', '')),
            filter_tool_messages=bool(data.get('filter_tool_messages', False)),
            filter_thinking=bool(data.get('filter_thinking', False)),
            dm_policy=_normalize_policy(data.get('dm_policy', 'open'), field_name='dm_policy'),
            group_policy=_normalize_policy(data.get('group_policy', 'open'), field_name='group_policy'),
            allow_from=[str(item) for item in allow_from],
            deny_message=str(data.get('deny_message', '')),
            require_mention=bool(data.get('require_mention', False)),
            media_dir=str(data.get('media_dir', '~/.copaw/media/wecom')),
            ping_interval_seconds=int(data.get('ping_interval_seconds', 20)),
            reconnect_delay_seconds=int(data.get('reconnect_delay_seconds', 5)),
            transport_factory=data.get('transport_factory'),
            websocket_url=str(data.get('websocket_url', 'wss://openws.work.weixin.qq.com')),
            auto_reconnect=bool(data.get('auto_reconnect', True)),
            auto_receive_background=bool(data.get('auto_receive_background', True)),
            token=str(data.get('token', '')),
            encoding_aes_key=str(data.get('encoding_aes_key', '')),
            receive_id=str(data.get('receive_id', '')),
            response_timeout_seconds=int(data.get('response_timeout_seconds', 10)),
            response_post_func=data.get('response_post_func'),
            media_fetch_func=data.get('media_fetch_func'),
        )

