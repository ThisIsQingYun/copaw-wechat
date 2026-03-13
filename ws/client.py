from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable
from uuid import uuid4

from wecom.config import WeComConfig
from wecom.models import InboundEnvelope


class WeComWebSocketClient:
    def __init__(self, *, config: WeComConfig, transport_factory, sleep_func: Callable[[float], Awaitable[Any]] | None = None):
        self._config = config
        self._transport_factory = transport_factory
        self._sleep = sleep_func or asyncio.sleep
        self._transport = None
        self._stopped = False
        self._background_tasks: list[asyncio.Task] = []

    @property
    def transport(self):
        return self._transport

    async def connect(self) -> None:
        candidate = self._transport_factory()
        self._transport = await candidate if inspect.isawaitable(candidate) else candidate
        self._stopped = False
        await self.send_command({
            'cmd': 'aibot_subscribe',
            'headers': {'req_id': self._new_req_id('subscribe')},
            'body': {
                'bot_id': self._config.bot_id,
                'secret': self._config.secret,
            },
        })

    async def send_command(self, command: dict) -> None:
        await self._require_transport().send_json(command)

    async def send_ping(self) -> None:
        await self.send_command({
            'cmd': 'ping',
            'headers': {'req_id': self._new_req_id('ping')},
        })

    async def receive_one(self) -> InboundEnvelope:
        payload = await self._require_transport().recv_json()
        return InboundEnvelope.from_dict(payload)

    async def dispatch_once(self, on_envelope) -> InboundEnvelope:
        envelope = await self.receive_one()
        result = on_envelope(envelope)
        if inspect.isawaitable(result):
            await result
        return envelope

    async def start_background(self, on_envelope):
        if self._background_tasks:
            return self._background_tasks
        self._background_tasks = [
            asyncio.create_task(self._receive_loop(on_envelope), name='wecom-receive-loop'),
            asyncio.create_task(self._heartbeat_loop(), name='wecom-heartbeat-loop'),
        ]
        return self._background_tasks

    async def run_forever(self, on_envelope, *, max_reconnects: int | None = None):
        reconnect_count = 0
        last_error: Exception | None = None

        while not self._stopped:
            reconnect_needed = False
            last_error = None
            try:
                if self._transport is None:
                    await self.connect()
                await self.start_background(on_envelope)
                results = await asyncio.gather(*self._background_tasks, return_exceptions=True)
                reconnect_needed = any(not isinstance(result, asyncio.CancelledError) and result is not None for result in results)
                for result in results:
                    if isinstance(result, Exception):
                        last_error = result
                        break
            except Exception as exc:
                reconnect_needed = True
                last_error = exc
            finally:
                self._background_tasks.clear()
                if self._transport is not None and not self._stopped:
                    await self._transport.close()
                    self._transport = None

            if self._stopped:
                break
            if not reconnect_needed:
                break
            if not self._config.auto_reconnect:
                if last_error is not None:
                    raise last_error
                break

            reconnect_count += 1
            if max_reconnects is not None and reconnect_count > max_reconnects:
                if last_error is not None:
                    raise last_error
                break
            await self._sleep(self._config.reconnect_delay_seconds)

    async def _receive_loop(self, on_envelope):
        while not self._stopped:
            await self.dispatch_once(on_envelope)

    async def _heartbeat_loop(self):
        while not self._stopped:
            await self._sleep(self._config.ping_interval_seconds)
            if self._stopped:
                break
            await self.send_ping()

    async def stop(self) -> None:
        self._stopped = True
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()
        if self._transport is not None:
            await self._transport.close()
            self._transport = None

    def should_reconnect(self) -> bool:
        return not self._stopped

    def _require_transport(self):
        if self._transport is None:
            raise RuntimeError('WebSocket transport has not been initialized')
        return self._transport

    @staticmethod
    def _new_req_id(prefix: str) -> str:
        return f'{prefix}-{uuid4().hex}'
