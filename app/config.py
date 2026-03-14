from __future__ import annotations

from dataclasses import dataclass, field
from os import getenv
from typing import Any, Mapping

from wecom.config import _normalize_policy

from .constants import (
    APP_CHANNEL_NAME,
    DEFAULT_API_BASE_URL,
    DEFAULT_CALLBACK_HOST,
    DEFAULT_CALLBACK_PATH,
    DEFAULT_CALLBACK_PORT,
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


_PROXY_ENV_KEYS = (
    ENV_APP_EGRESS_PROXY_URL,
    'WECOM_EGRESS_PROXY_URL',
    'HTTPS_PROXY',
    'ALL_PROXY',
    'HTTP_PROXY',
)


def _resolve_proxy_url(value: Any) -> str:
    direct = str(value or '').strip()
    if direct:
        return direct
    for env_key in _PROXY_ENV_KEYS:
        candidate = getenv(env_key, '').strip()
        if candidate:
            return candidate
    return ''


def _normalize_callback_path(value: Any) -> str:
    raw = str(value or DEFAULT_CALLBACK_PATH).strip() or DEFAULT_CALLBACK_PATH
    if not raw.startswith('/'):
        raw = f'/{raw}'
    return raw


def _coerce_int(value: Any, *, default: int) -> int:
    raw = str(value).strip() if value is not None else ''
    if not raw:
        return default
    return int(raw)


@dataclass(slots=True)
class WeComAppConfig:
    corp_id: str
    agent_secret: str
    agent_id: int
    channel_name: str = APP_CHANNEL_NAME
    enabled: bool = True
    bot_prefix: str = ''
    filter_tool_messages: bool = False
    filter_thinking: bool = False
    dm_policy: str = 'open'
    group_policy: str = 'open'
    allow_from: list[str] = field(default_factory=list)
    deny_message: str = ''
    require_mention: bool = False
    media_dir: str = '~/.copaw/media/wecom_app'
    token: str = ''
    encoding_aes_key: str = ''
    receive_id: str = ''
    callback_host: str = DEFAULT_CALLBACK_HOST
    callback_port: int = DEFAULT_CALLBACK_PORT
    callback_path: str = DEFAULT_CALLBACK_PATH
    callback_base_url: str = ''
    auto_start_callback_server: bool = True
    request_timeout_seconds: int = 10
    token_refresh_skew_seconds: int = 300
    api_base_url: str = DEFAULT_API_BASE_URL
    egress_proxy_url: str = ''
    api_request_func: Any = None
    media_fetch_func: Any = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> 'WeComAppConfig':
        corp_id = str(data.get('corp_id', ''))
        agent_secret = str(data.get('agent_secret') or data.get('corp_secret') or '')
        allow_from = data.get('allow_from') or []
        if not isinstance(allow_from, list):
            allow_from = list(allow_from)

        return cls(
            corp_id=corp_id,
            agent_secret=agent_secret,
            agent_id=_coerce_int(data.get('agent_id'), default=0),
            channel_name=str(data.get('channel_name', APP_CHANNEL_NAME)),
            enabled=bool(data.get('enabled', True)),
            bot_prefix=str(data.get('bot_prefix', '')),
            filter_tool_messages=bool(data.get('filter_tool_messages', False)),
            filter_thinking=bool(data.get('filter_thinking', False)),
            dm_policy=_normalize_policy(data.get('dm_policy', 'open'), field_name='dm_policy'),
            group_policy=_normalize_policy(data.get('group_policy', 'open'), field_name='group_policy'),
            allow_from=[str(item) for item in allow_from],
            deny_message=str(data.get('deny_message', '')),
            require_mention=bool(data.get('require_mention', False)),
            media_dir=str(data.get('media_dir', '~/.copaw/media/wecom_app')),
            token=str(data.get('token', '')),
            encoding_aes_key=str(data.get('encoding_aes_key', '')),
            receive_id=str(data.get('receive_id') or corp_id),
            callback_host=str(data.get('callback_host', DEFAULT_CALLBACK_HOST)),
            callback_port=_coerce_int(data.get('callback_port'), default=DEFAULT_CALLBACK_PORT),
            callback_path=_normalize_callback_path(data.get('callback_path', DEFAULT_CALLBACK_PATH)),
            callback_base_url=str(data.get('callback_base_url', '')),
            auto_start_callback_server=bool(data.get('auto_start_callback_server', True)),
            request_timeout_seconds=_coerce_int(data.get('request_timeout_seconds'), default=10),
            token_refresh_skew_seconds=_coerce_int(data.get('token_refresh_skew_seconds'), default=300),
            api_base_url=str(data.get('api_base_url', DEFAULT_API_BASE_URL)).rstrip('/'),
            egress_proxy_url=_resolve_proxy_url(data.get('egress_proxy_url')),
            api_request_func=data.get('api_request_func'),
            media_fetch_func=data.get('media_fetch_func'),
        )

    @classmethod
    def from_env(cls) -> 'WeComAppConfig':
        return cls.from_mapping(
            {
                'corp_id': getenv(ENV_APP_CORP_ID, ''),
                'agent_secret': getenv(ENV_APP_SECRET, ''),
                'agent_id': getenv(ENV_APP_AGENT_ID, ''),
                'token': getenv(ENV_APP_CALLBACK_TOKEN, ''),
                'encoding_aes_key': getenv(ENV_APP_ENCODING_AES_KEY, ''),
                'receive_id': getenv(ENV_APP_RECEIVE_ID, ''),
                'callback_host': getenv(ENV_APP_CALLBACK_HOST, DEFAULT_CALLBACK_HOST),
                'callback_port': getenv(ENV_APP_CALLBACK_PORT, str(DEFAULT_CALLBACK_PORT)),
                'callback_path': getenv(ENV_APP_CALLBACK_PATH, DEFAULT_CALLBACK_PATH),
                'egress_proxy_url': getenv(ENV_APP_EGRESS_PROXY_URL, ''),
            }
        )
