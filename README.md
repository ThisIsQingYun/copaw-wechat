# copaw-wechat

这是一个面向 `copaw` 的企业微信自定义渠道项目。当前 `wecom/` 目录本身就是最终交付目录，可以直接作为独立 GitHub 仓库根目录使用。

当前同时提供两个独立渠道：

- `wecom`：企微智能机器人
- `wecom_app`：企微自建应用

远程仓库地址：

- `https://github.com/ThisIsQingYun/copaw-wechat.git`

## 部署教程

请直接在 `copaw` 的自定义渠道目录下克隆本仓库，并把目标目录名固定为 `wecom`。

原因：`copaw` 扫描自定义渠道时，会按目录名导入模块；仓库名 `copaw-wechat` 带连字符，不能直接作为 Python 包名使用，所以必须显式克隆到 `wecom/`。

### 1. 进入自定义渠道目录

```bash
cd ~/.copaw/custom_channels
```

### 2. 克隆仓库到 `wecom/`

```bash
git clone https://github.com/ThisIsQingYun/copaw-wechat.git wecom
```

### 3. 进入插件目录

```bash
cd wecom
```

### 4. 安装依赖

```bash
pip install -r requirements.txt
```

### 5. 修改 `copaw` 配置文件

把 [config.example.json](D:/Software/codex/copaw-wechat/wecom/config.example.json) 里的对应渠道配置合并进你的 `config.json`。

推荐直接同时预写两个渠道：

```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "bot_prefix": "",
      "filter_tool_messages": false,
      "filter_thinking": false,
      "bot_id": "",
      "secret": "",
      "token": "",
      "encoding_aes_key": "",
      "receive_id": "",
      "channel_name": "wecom",
      "dm_policy": "open",
      "group_policy": "open",
      "allow_from": [],
      "deny_message": "",
      "require_mention": false,
      "media_dir": "~/.copaw/media/wecom",
      "websocket_url": "wss://openws.work.weixin.qq.com",
      "response_timeout_seconds": 10,
      "ping_interval_seconds": 20,
      "reconnect_delay_seconds": 5,
      "auto_reconnect": true,
      "auto_receive_background": true
    },
    "wecom_app": {
      "enabled": false,
      "bot_prefix": "",
      "filter_tool_messages": false,
      "filter_thinking": false,
      "corp_id": "",
      "agent_secret": "",
      "agent_id": 0,
      "token": "",
      "encoding_aes_key": "",
      "receive_id": "",
      "channel_name": "wecom_app",
      "dm_policy": "open",
      "group_policy": "open",
      "allow_from": [],
      "deny_message": "",
      "require_mention": false,
      "media_dir": "~/.copaw/media/wecom_app",
      "callback_host": "0.0.0.0",
      "callback_port": 19091,
      "callback_path": "/wecom/app/callback",
      "callback_base_url": "",
      "auto_start_callback_server": true,
      "request_timeout_seconds": 10,
      "token_refresh_skew_seconds": 300,
      "api_base_url": "https://qyapi.weixin.qq.com",
      "egress_proxy_url": ""
    }
  }
}
```

## 两种渠道的必填参数

### `wecom` 企微智能机器人

需要你自己填写：

- `bot_id`
- `secret`
- `token`
- `encoding_aes_key`
- `receive_id`

说明：

- 如果你只使用长连接模式，`token`、`encoding_aes_key`、`receive_id` 可以先留空。

### `wecom_app` 企微自建应用

需要你自己填写：

- `corp_id`
- `agent_secret`
- `agent_id`
- `token`
- `encoding_aes_key`
- `receive_id`

说明：

- `receive_id` 默认可直接填写企业 `corp_id`。
- `agent_secret` 也兼容老写法 `corp_secret`，但后续文档统一使用 `agent_secret`。
- `callback_base_url` 只是便于记录公网入口，不参与插件内部监听。

## Web 控制台说明

CoPaw Web 对自定义渠道不会自动生成企微专用表单。建议先把上面的字段按顺序写进 `config.json`，再到 Web 里编辑。

建议字段顺序保持：

- `enabled`
- `bot_prefix`
- `filter_tool_messages`
- `filter_thinking`
- 然后再写企微必填参数

这样 Web 控制台里最重要的开关和凭证会排在最前面。

另外：

- `dm_policy` 和 `group_policy` 的标准值是 `open`、`allowlist`
- 插件也接受中文填写 `开放`、`白名单列表`，并会自动转换

## 当前支持的消息类型

| 频道 | 接收文本 | 接收图片 | 接收视频 | 接收音频 | 接收文件 | 发送文本 | 发送图片 | 发送视频 | 发送音频 | 发送文件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| wecom | 是 | 是 | 否 | 部分 | 是 | 是 | 否 | 否 | 否 | 否 |
| wecom_app | 是 | 是 | 是 | 是 | 是 | 是 | 是 | 是 | 是 | 是 |

补充说明：

- `wecom` 的 `接收音频 = 部分` 表示当前支持语音转写接入，但不单独输出完整语音文件。
- `wecom_app` 的富媒体发送通过企业微信自建应用主动 API 实现，图片、语音、视频、文件都会先上传媒体再发送。
- `wecom_app` 的群聊会话发送走 `appchat` 系列接口，模板卡片不走 `appchat`。

## 自建应用网络要求

`wecom_app` 本地部署时，要分清两类网络需求：

### 1. 入站回调

企业微信必须能访问到你的 callback URL。

这通常意味着你至少需要其中一种：

- 公网服务器
- 反向代理
- 内网穿透 / 隧道

### 2. 出站 API

你的服务访问 `https://qyapi.weixin.qq.com` 时，如果公网出口 IP 不固定，可能遇到 `60020 not allow to access from your ip`。

这时再配置正向代理：

- `egress_proxy_url`

可直接填到 `wecom_app` 配置里，也兼容这些环境变量：

- `WECOM_APP_EGRESS_PROXY_URL`
- `WECOM_EGRESS_PROXY_URL`
- `HTTPS_PROXY`
- `ALL_PROXY`
- `HTTP_PROXY`

也就是说：

- 公网入口解决“企微能不能打进来”
- 正向代理解决“你的服务能不能稳定打出去”

这两件事不是一回事。

## 插件更新方式

如果你已经通过 `git clone` 安装了本插件，后续更新直接在 `wecom/` 目录执行：

```bash
cd ~/.copaw/custom_channels/wecom
git pull --ff-only origin main
pip install -r requirements.txt
```

更新后建议再做两件事：

- 对照最新的 `README.md` 或 [config.example.json](D:/Software/codex/copaw-wechat/wecom/config.example.json)，确认你的 `config.json` 是否需要补充新字段
- 重启 `copaw`

## 项目结构

```text
wecom/
|-- __init__.py
|-- README.md
|-- requirements.txt
|-- config.py
|-- config.example.json
|-- channel.py
|-- channel_service.py
|-- media_store.py
|-- crypto.py
|-- webhook.py
|-- active_reply.py
|-- docs_api.py
|-- models.py
|-- constants.py
|-- runtime_compat.py
|-- app/
|   |-- __init__.py
|   |-- constants.py
|   |-- config.py
|   |-- models.py
|   |-- parser.py
|   |-- callback.py
|   |-- api_client.py
|   |-- media_store.py
|   |-- server.py
|   `-- channel.py
|-- cards/
|   |-- __init__.py
|   `-- builders.py
|-- parsers/
|   |-- __init__.py
|   |-- inbound.py
|   `-- outbound.py
|-- ws/
|   |-- __init__.py
|   |-- client.py
|   `-- transport.py
`-- tests/
```

## 关键文件说明

- `channel.py`：企微智能机器人渠道主入口
- `app/channel.py`：企微自建应用渠道主入口
- `app/api_client.py`：自建应用 `access_token`、消息发送、群聊会话、媒体上传下载
- `app/callback.py`：自建应用 callback 验签、解密、加密回复
- `app/server.py`：自建应用内置 callback HTTP 服务
- `app/media_store.py`：自建应用入站媒体下载落盘
- `runtime_compat.py`：运行时兼容层，统一适配 `copaw` 和 `agentscope_runtime`

## 初始化并推送到 GitHub

如果你后续准备把当前这个 `wecom/` 目录本身作为 GitHub 仓库根目录推送，可以在 `wecom/` 目录下执行：

```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/ThisIsQingYun/copaw-wechat.git
git push -u origin main
```
