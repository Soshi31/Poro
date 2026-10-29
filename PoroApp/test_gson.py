import urllib.request, re, json
req = urllib.request.Request('https://tactics.tools/player/eune/Soshi/2609', headers={'User-Agent': 'Mozilla/5.0'})
res = urllib.request.urlopen(req).read().decode('utf-8')
match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', res)
if match:
    data = json.loads(match.group(1))
    print(data['props']['pageProps'].keys())
