import requests
import pprint

params = '''{User-Agent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"}'''

response = requests.post("https://httpbin.org/post", params=params)
print(response.status_code)
pprint.pprint(response.content)
print("\n")
print(response.request.headers)
