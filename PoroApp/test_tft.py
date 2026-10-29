import urllib.request, urllib.error
urls = [
    'https://lolchess.gg/api/profile/euw/Soshi/2609',
    'https://lolchess.gg/api/profile/euw1/Soshi/2609',
    'https://lolchess.gg/api/profile/euw1/Soshi-2609',
]
for u in urls:
    try:
        req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req).read().decode('utf-8')
        print(u, 'SUCCESS:', res[:100])
    except urllib.error.HTTPError as e:
        print(u, 'FAILED:', e.code)
    except Exception as e:
        print(u, 'ERROR:', e)
