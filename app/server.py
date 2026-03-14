from __future__ import annotations

from typing import Awaitable, Callable

from aiohttp import web


class WeComAppCallbackServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        path: str,
        on_verify: Callable[[dict[str, str]], str],
        on_callback: Callable[[dict[str, str], str], Awaitable[str | None]],
    ):
        self._host = host
        self._port = port
        self._path = path
        self._on_verify = on_verify
        self._on_callback = on_callback
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        if self._runner is not None:
            return
        app = web.Application()
        app.router.add_get(self._path, self._handle_verify)
        app.router.add_post(self._path, self._handle_callback)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self._host, port=self._port)
        await self._site.start()

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _handle_verify(self, request: web.Request) -> web.Response:
        plaintext = self._on_verify(dict(request.query))
        return web.Response(text=plaintext, content_type='text/plain')

    async def _handle_callback(self, request: web.Request) -> web.Response:
        body_text = await request.text()
        reply = await self._on_callback(dict(request.query), body_text)
        if reply and reply.lstrip().startswith('<xml>'):
            return web.Response(text=reply, content_type='application/xml')
        return web.Response(text=reply or 'success', content_type='text/plain')
