from wecom.app.parser import build_native_payload_from_callback, parse_plaintext_xml


TEXT_XML = """
<xml>
  <ToUserName><![CDATA[ww1234567890]]></ToUserName>
  <FromUserName><![CDATA[zhangsan]]></FromUserName>
  <CreateTime>1710000000</CreateTime>
  <MsgType><![CDATA[text]]></MsgType>
  <Content><![CDATA[你好，自建应用]]></Content>
  <MsgId>1234567890123456</MsgId>
  <AgentID>1000001</AgentID>
</xml>
""".strip()


EVENT_XML = """
<xml>
  <ToUserName><![CDATA[ww1234567890]]></ToUserName>
  <FromUserName><![CDATA[zhangsan]]></FromUserName>
  <CreateTime>1710000000</CreateTime>
  <MsgType><![CDATA[event]]></MsgType>
  <Event><![CDATA[enter_agent]]></Event>
  <AgentID>1000001</AgentID>
</xml>
""".strip()


FILE_XML = """
<xml>
  <ToUserName><![CDATA[ww1234567890]]></ToUserName>
  <FromUserName><![CDATA[zhangsan]]></FromUserName>
  <CreateTime>1710000000</CreateTime>
  <MsgType><![CDATA[file]]></MsgType>
  <MediaId><![CDATA[MEDIA_ID_001]]></MediaId>
  <FileName><![CDATA[report.pdf]]></FileName>
  <MsgId>1234567890123457</MsgId>
  <AgentID>1000001</AgentID>
</xml>
""".strip()


def test_parse_text_callback_xml_into_native_payload():
    parsed = parse_plaintext_xml(TEXT_XML)
    payload = build_native_payload_from_callback(parsed, channel_name='wecom_app')

    assert payload['sender_id'] == 'zhangsan'
    assert payload['text'] == '你好，自建应用'
    assert payload['meta']['msgid'] == '1234567890123456'
    assert payload['meta']['agent_id'] == '1000001'


def test_parse_event_callback_xml_into_event_payload():
    parsed = parse_plaintext_xml(EVENT_XML)
    payload = build_native_payload_from_callback(parsed, channel_name='wecom_app')

    assert payload['text'] == ''
    assert payload['event']['eventtype'] == 'enter_agent'


def test_parse_file_callback_xml_into_attachment_payload():
    parsed = parse_plaintext_xml(FILE_XML)
    payload = build_native_payload_from_callback(parsed, channel_name='wecom_app')

    assert payload['attachments'][0]['type'] == 'file'
    assert payload['attachments'][0]['media_id'] == 'MEDIA_ID_001'
    assert payload['attachments'][0]['file_name'] == 'report.pdf'
