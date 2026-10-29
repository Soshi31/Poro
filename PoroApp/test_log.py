import urllib.request, re, json
try:
    url = 'https://www.leagueofgraphs.com/tft/summoner/eune/Soshi-2609'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'})
    res = urllib.request.urlopen(req).read().decode('utf-8')
    print("LOG length:", len(res))
    print(re.findall(r'placement.*?(\d)', res, re.IGNORECASE)[:10])
except Exception as e:
    print("LOG error:", e)
