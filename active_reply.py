from __future__ import annotations

import inspect
from typing import Any, Callable

import httpx

from wecom.models import OutboundMessage
from wecom.parsers.outbound import build_response_url_body


class ResponseUrlReplyClient:
    def __init__(self, *, post_func: Callable[..., Any] | None = None, timeout_seconds: int = 10):
        self._post_func = post_func
        self._timeout_seconds = timeout_seconds

    async def send_payload(self, response_url: str, payload: dict) -> Any:
        if self._post_func is None:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(response_url, json=payload)
        else:
            response = self._post_func(response_url, payload, self._timeout_seconds)
            if inspect.isawaitable(response):
                response = await response

        if hasattr(response, 'json'):
            return response.json()
        return response

    async def send_message(self, response_url: str, message: OutboundMessage) -> Any:
        return await self.send_payload(response_url, build_response_url_body(message))

    async def send_markdown(self, response_url: str, content: str, feedback_id: str | None = None) -> Any:
        markdown = {'content': content}
        if feedback_id:
            markdown['feedback'] = {'id': feedback_id}
        return await self.send_payload(response_url, {'msgtype': 'markdown', 'markdown': markdown})

    async def send_template_card(self, response_url: str, template_card: dict) -> Any:
        return await self.send_payload(response_url, {'msgtype': 'template_card', 'template_card': template_card})
