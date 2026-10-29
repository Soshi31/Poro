import urllib.request, re, json
try:
    # the op.gg api often uses standard formats
    url = 'https://tft.op.gg/api/player/eune/Soshi-2609'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req).read().decode('utf-8')
    print("tft.op.gg API:", res[:200])
except Exception as e:
    print("tft.op.gg API error:", e)

try:
    # Maybe mobalytics?
    url = 'https://app.mobalytics.gg/api/tft/v1/summoner/eune/Soshi-2609'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req).read().decode('utf-8')
    print("mobalytics API:", res[:200])
except Exception as e:
    print("mobalytics API error:", e)
