"""Send already generated acceptance media to the configured owner only."""
import json
import mimetypes
from pathlib import Path
import uuid
from api_client import BASE, Dashboard

client = Dashboard()
owner = str(json.loads((BASE / 'secrets/credentials.json').read_text())['owner_qq'])
runtime = json.loads((BASE / 'astrbot/data/deployment-validation.json').read_text())
media = [('record', runtime['tts']['audio_file']), ('image', '/AstrBot/data/temp/deployment-sf_draw.png'),
         ('image', '/AstrBot/data/temp/deployment-sf_selfie.png')]
results = []
client.request('POST', '/im/messages', {'umo': 'qq:FriendMessage:' + owner,
    'message': '部署验收：下面依次是系统音色语音、画图和角色自拍测试。请确认能否播放语音、打开两张图片。'})
for kind, filename in media:
    path = BASE / 'astrbot' / Path(filename).relative_to('/AstrBot')
    boundary = 'Dafeiyu' + uuid.uuid4().hex
    body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + path.name + '"\r\nContent-Type: ' +
            (mimetypes.guess_type(path.name)[0] or 'application/octet-stream') + '\r\n\r\n').encode() + path.read_bytes() + ('\r\n--' + boundary + '--\r\n').encode()
    attachment = client.request('POST', '/file', raw=body, content_type='multipart/form-data; boundary=' + boundary)
    attachment_id = attachment.get('attachment_id') or attachment.get('id')
    if not attachment_id:
        raise RuntimeError('Upload response has no attachment id; fields=' + str(list(attachment)))
    client.request('POST', '/im/messages', {'umo': 'qq:FriendMessage:' + owner, 'message': [{'type': kind, 'attachment_id': attachment_id}]})
    results.append({'type': kind, 'file': path.name, 'api_accepted': True})
(BASE / 'incoming/outbound-media-validation.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results))
