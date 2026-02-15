import requests
import pprint

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}
payload = {
  "device": "NanoPi R4S",
  "mode": "vpn",
  "active": True
}
response = requests.post("https://httpbin.org/post", headers=headers, json=payload)
print(response.status_code)
pprint.pprint(response.json())
print("\n")
print(response.request.headers)
