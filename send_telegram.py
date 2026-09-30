#!/usr/bin/env python3
import urllib.request, json
with open('/tmp/telegram_msg.txt') as f:
    text = f.read()
with open('config/config.toml', 'rb') as f:
    import tomllib
    cfg = tomllib.load(f)
    token = cfg['telegram']['bot_token']
    chat = cfg['telegram']['chat_id']
url = f"https://api.telegram.org/bot{token}/sendMessage"
req = urllib.request.Request(url, data=json.dumps({"chat_id": chat, "text": text}).encode(), headers={"Content-Type":"application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=15) as resp:
    body = json.loads(resp.read())
    print("ok:", body.get("ok"), "desc:", body.get("description"))
