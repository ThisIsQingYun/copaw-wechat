from __future__ import annotations

import asyncio
import logging
from typing import Any


logger = logging.getLogger('copaw.app.channels.wecom.session_dispatch')


class LatestSessionTaskMixin:
    def _init_latest_session_dispatch(self) -> None:
        self._session_tasks: dict[str, asyncio.Task] = {}
        self._session_tasks_lock = asyncio.Lock()

    async def consume_one(self, payload) -> None:
        session_key = self._resolve_session_task_key(payload)
        if not session_key:
            await self._consume_one_request(payload)
            return

        previous_task = None
        new_task = asyncio.create_task(
            self._run_latest_session_payload(session_key, payload),
            name=f'{getattr(self, "channel", "channel")}-session-{session_key[:48]}',
        )
        async with self._session_tasks_lock:
            previous_task = self._session_tasks.get(session_key)
            self._session_tasks[session_key] = new_task

        if previous_task is not None and not previous_task.done():
            logger.info(
                '%s canceling previous in-flight session task: session=%s',
                getattr(self, 'channel', 'channel'),
                session_key[:96],
            )
            previous_task.cancel()

    async def _run_latest_session_payload(self, session_key: str, payload: Any) -> None:
        current_task = asyncio.current_task()
        try:
            await self._consume_one_request(payload)
        except asyncio.CancelledError:
            logger.info(
                '%s session task canceled in favor of a newer message: session=%s',
                getattr(self, 'channel', 'channel'),
                session_key[:96],
            )
            raise
        finally:
            async with self._session_tasks_lock:
                if self._session_tasks.get(session_key) is current_task:
                    self._session_tasks.pop(session_key, None)

    async def _cancel_all_session_tasks(self) -> None:
        async with self._session_tasks_lock:
            tasks = list(self._session_tasks.values())
            self._session_tasks.clear()
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _resolve_session_task_key(self, payload: Any) -> str:
        if isinstance(payload, dict):
            meta = dict(payload.get('meta') or {})
            session_id = payload.get('session_id') or meta.get('session_id')
            if session_id:
                return str(session_id)
            sender_id = str(payload.get('sender_id') or '')
            resolver = getattr(self, 'resolve_session_id', None)
            if callable(resolver):
                try:
                    resolved = resolver(sender_id, meta)
                except Exception:
                    resolved = ''
                if resolved:
                    return str(resolved)
            if sender_id:
                return sender_id
        session_id = getattr(payload, 'session_id', '') or getattr(payload, 'sender_id', '')
        return str(session_id or '')
