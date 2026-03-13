from __future__ import annotations

from importlib import import_module


class MissingRuntimeDependency(RuntimeError):
    pass


def load_copaw_symbols() -> dict[str, object]:
    try:
        base_module = import_module('copaw.app.channels.base')
        schema_module = import_module('copaw.app.channels.schema')
        runtime_module = import_module('agentscope_runtime.engine.schemas.agent_schemas')
    except ModuleNotFoundError as exc:
        raise MissingRuntimeDependency(
            'copaw runtime dependencies are missing. Install copaw and agentscope_runtime '
            'in the target environment before loading the WeCom channel plugin.'
        ) from exc

    return {
        'BaseChannel': getattr(base_module, 'BaseChannel'),
        'ChannelType': getattr(schema_module, 'ChannelType'),
        'ContentType': getattr(runtime_module, 'ContentType'),
        'TextContent': getattr(runtime_module, 'TextContent'),
        'ImageContent': getattr(runtime_module, 'ImageContent', None),
        'AudioContent': getattr(runtime_module, 'AudioContent', None),
        'FileContent': getattr(runtime_module, 'FileContent', None),
    }
