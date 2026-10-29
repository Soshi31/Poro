import urllib.request, json
urls = [
    'https://tft-api.op.gg/api/v1/summoners/eune/Soshi-2609',
    'https://tft-api.op.gg/api/v1/summoners/eune/Soshi-2609/matches',
    'https://tft-api.op.gg/api/v1.0/internal/bypass/summoners/eune/Soshi-2609/matches'
]
for u in urls:
    try:
        req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req).read().decode('utf-8')
        print(u, 'SUCCESS:', res[:100])
    except Exception as e:
        print(u, 'FAILED:', e)
