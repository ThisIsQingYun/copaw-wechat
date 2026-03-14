from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Awaitable, Callable
from uuid import uuid4

from wecom.config import WeComConfig
from wecom.models import InboundEnvelope

logger = logging.getLogger('copaw.app.channels.wecom.ws.client')


class WeComWebSocketClient:
    def __init__(self, *, config: WeComConfig, transport_factory, sleep_func: Callable[[float], Awaitable[Any]] | None = None):
        self._config = config
        self._transport_factory = transport_factory
        self._sleep = sleep_func or asyncio.sleep
        self._transport = None
        self._stopped = False
        self._background_tasks: list[asyncio.Task] = []
        self._pending_acks: dict[str, asyncio.Future] = {}

    @property
    def transport(self):
        return self._transport

    async def connect(self) -> None:
        logger.info('wecom websocket opening: url=%s', self._config.websocket_url)
        candidate = self._transport_factory()
        self._transport = await candidate if inspect.isawaitable(candidate) else candidate
        self._stopped = False
        await self.send_command(
            {
                'cmd': 'aibot_subscribe',
                'headers': {'req_id': self._new_req_id('subscribe')},
                'body': {
                    'bot_id': self._config.bot_id,
                    'secret': self._config.secret,
                },
            },
            wait_for_ack=False,
        )
        logger.info('wecom websocket subscribe sent: bot_id=%s', (self._config.bot_id or '')[:12])

    async def send_command(self, command: dict, *, wait_for_ack: bool = True) -> InboundEnvelope | None:
        req_id = str(((command.get('headers') or {}).get('req_id')) or '')
        pending_ack = None
        if wait_for_ack and req_id:
            pending_ack = asyncio.get_running_loop().create_future()
            self._pending_acks[req_id] = pending_ack
        await self._require_transport().send_json(command)
        if pending_ack is None:
            return None
        try:
            envelope = await asyncio.wait_for(pending_ack, timeout=self._config.response_timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning(
                'wecom websocket ack timeout: cmd=%s req_id=%s timeout=%s',
                command.get('cmd', ''),
                req_id,
                self._config.response_timeout_seconds,
            )
            return None
        finally:
            existing = self._pending_acks.get(req_id)
            if existing is pending_ack:
                self._pending_acks.pop(req_id, None)
        return envelope

    async def send_ping(self) -> None:
        await self.send_command(
            {
                'cmd': 'ping',
                'headers': {'req_id': self._new_req_id('ping')},
            },
            wait_for_ack=False,
        )

    async def receive_one(self) -> InboundEnvelope:
        payload = await self._require_transport().recv_json()
        envelope = InboundEnvelope.from_dict(payload)
        if envelope.is_heartbeat():
            logger.debug('wecom websocket heartbeat received: req_id=%s', envelope.req_id)
        else:
            body = envelope.body or {}
            body_keys = ','.join(sorted(str(key) for key in body.keys())) or '-'
            logger.info(
                'wecom websocket frame received: cmd=%s req_id=%s body_keys=%s errcode=%s errmsg=%s',
                envelope.cmd,
                envelope.req_id,
                body_keys,
                body.get('errcode', ''),
                body.get('errmsg', ''),
            )
        return envelope

    async def receive_dispatchable(self) -> InboundEnvelope:
        while True:
            envelope = await self.receive_one()
            if self._resolve_pending_ack(envelope):
                continue
            if self._is_empty_frame(envelope):
                logger.debug('wecom websocket empty frame ignored: req_id=%s', envelope.req_id)
                continue
            return envelope

    async def dispatch_once(self, on_envelope) -> InboundEnvelope:
        envelope = await self.receive_dispatchable()
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
                logger.warning('wecom websocket loop error, will reconnect=%s error=%s', self._config.auto_reconnect, exc)
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
            logger.info('wecom websocket reconnecting after %s seconds', self._config.reconnect_delay_seconds)
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
        logger.info('wecom websocket stopping')
        self._stopped = True
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()
        if self._transport is not None:
            await self._transport.close()
            self._transport = None
        logger.info('wecom websocket stopped')

    def should_reconnect(self) -> bool:
        return not self._stopped

    def _require_transport(self):
        if self._transport is None:
            raise RuntimeError('WebSocket transport has not been initialized')
        return self._transport

    def _resolve_pending_ack(self, envelope: InboundEnvelope) -> bool:
        req_id = envelope.req_id
        if not req_id:
            return False
        future = self._pending_acks.get(req_id)
        if future is None:
            return False
        if not future.done():
            future.set_result(envelope)
        body = envelope.body or {}
        body_keys = ','.join(sorted(str(key) for key in body.keys())) or '-'
        logger.info(
            'wecom websocket ack received: cmd=%s req_id=%s body_keys=%s errcode=%s errmsg=%s',
            envelope.cmd,
            req_id,
            body_keys,
            body.get('errcode', ''),
            body.get('errmsg', ''),
        )
        return True

    @staticmethod
    def _is_empty_frame(envelope: InboundEnvelope) -> bool:
        return not envelope.cmd and not (envelope.body or {})

    @staticmethod
    def _new_req_id(prefix: str) -> str:
        return f'{prefix}-{uuid4().hex}'




