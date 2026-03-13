from __future__ import annotations

from typing import Any, Callable

import aiohttp

from wecom.config import WeComConfig


class AioHttpWebSocketTransport:
    def __init__(self, *, websocket, session: aiohttp.ClientSession | None):
        self._websocket = websocket
        self._session = session

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self._websocket.send_json(payload)

    async def recv_json(self) -> dict[str, Any]:
        return await self._websocket.receive_json()

    async def close(self) -> None:
        await self._websocket.close()
        if self._session is not None:
            await self._session.close()


def build_aiohttp_transport_factory(
    config: WeComConfig,
    *,
    session_factory: Callable[[], aiohttp.ClientSession] | None = None,
):
    async def factory() -> AioHttpWebSocketTransport:
        session = session_factory() if session_factory is not None else aiohttp.ClientSession()
        websocket = await session.ws_connect(config.websocket_url)
        return AioHttpWebSocketTransport(websocket=websocket, session=session)

    return factory


def resolve_transport_factory(config: WeComConfig):
    return config.transport_factory or build_aiohttp_transport_factory(config)
