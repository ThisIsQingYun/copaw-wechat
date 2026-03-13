# copaw-wechat

这是一个面向 `copaw` 的企业微信智能机器人自定义渠道项目。当前目录本身就可以作为独立 GitHub 仓库根目录使用。

远程仓库地址：

- `https://github.com/ThisIsQingYun/copaw-wechat.git`

## 部署教程

请直接在 `copaw` 的自定义渠道目录下克隆这个仓库，并且把目标目录名固定为 `wecom`。

原因：`copaw` 扫描自定义渠道时，会按目录名导入模块；你的仓库名是 `copaw-wechat`，默认克隆目录名带连字符，不能直接作为 Python 包名使用，所以这里必须显式克隆到 `wecom/`。

### 1. 进入自定义渠道目录

```bash
cd ~/.copaw/custom_channels
```

如果你使用的是当前工作目录型 `copaw` 项目，就进入对应项目下的 `custom_channels/`。

### 2. 克隆远程仓库到 `wecom/`

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

把下面这段配置合并进你的 `config.json` 的 `channels` 节点：

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
    }
  }
}
```

需要你自己填写的字段：

- `bot_id`
- `secret`
- `token`
- `encoding_aes_key`
- `receive_id`

说明：

- 如果你只使用长连接模式，`token`、`encoding_aes_key`、`receive_id` 可以先留空。
- 建议按上面的顺序把字段写进 `config.json`；CoPaw Web 对自定义渠道通常会沿用现有 key 的顺序展示参数，这样 `enabled`、`bot_prefix`、`filter_tool_messages`、`filter_thinking` 会置顶，企微必填项会紧随其后。
- `media_dir` 用于保存接收到的图片和文件。
- Web 控制台不会自动生成自定义渠道专用表单，建议先把上面的字段预写进 `config.json`，再到 Web 里编辑。
- `dm_policy` 和 `group_policy` 的标准值与内置渠道一致：`open`、`allowlist`。
- 为了兼容 Web 中自定义渠道的文本输入方式，插件也接受中文填写：`开放`、`白名单列表`，并会自动转换成 `open`、`allowlist`。

## 插件更新方式

如果你已经通过 `git clone` 安装了本插件，后续更新直接在 `wecom/` 目录执行：

```bash
cd ~/.copaw/custom_channels/wecom
git pull --ff-only origin main
pip install -r requirements.txt
```

更新后建议再做两件事：

- 对照最新的 `README.md` 或 `config.example.json`，确认你的 `config.json` 里是否需要补充新字段。
- 重启 `copaw`，让新版本插件重新加载。

如果你的本地仓库改过文件，`git pull` 前请先自行提交、暂存或处理冲突。

## 当前支持的消息类型

| 频道 | 接收文本 | 接收图片 | 接收视频 | 接收音频 | 接收文件 | 发送文本 | 发送图片 | 发送视频 | 发送音频 | 发送文件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| wecom | 是 | 是 | 否 | 部分 | 是 | 是 | 否 | 否 | 否 | 否 |

补充说明：

- `接收音频 = 部分` 的含义是：当前支持企微语音消息的转写内容接入，但还不生成独立音频文件。
- 发送侧当前支持文本相关能力，包括 `text`、`markdown`、`stream`、`template_card`、欢迎语和卡片更新；表格里“发送文本”按“通用文本回复能力”统计。
- 当前 `media_dir` 会落盘 `image` 和 `file` 类型附件；如果长连接回调里附件带 `aeskey`，插件会先解密再保存。
- `发送图片/视频/音频/文件` 当前为否，主要是因为企微智能机器人官方发送/回复文档未开放这些发送消息体类型。

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
|-- utils.py
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
    |-- test_config.py
    `-- test_media_store.py
```

## 关键文件说明

- `channel.py`：`copaw` 渠道主入口
- `config.py`：渠道配置模型与策略值标准化
- `media_store.py`：图片和文件下载、解密、落盘
- `webhook.py`：Webhook 加解密与回调处理
- `active_reply.py`：`response_url` 主动回复
- `docs_api.py`：企微文档 / 智能表格工具封装
- `ws/`：长连接客户端与传输层
- `parsers/`：入站和出站协议解析
- `cards/`：模板卡片构造器

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

如果你是从一个空目录第一次手工初始化仓库，也可以参考你原来的命令流程；但当前目录已经有 `README.md`，所以通常不需要再执行：

```bash
echo "# copaw-wechat" >> README.md
```

