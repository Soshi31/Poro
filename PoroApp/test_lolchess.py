import urllib.request, re
try:
    req = urllib.request.Request('https://lolchess.gg/profile/eune/Soshi-2609/set12/matches', headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req).read().decode('utf-8')
    print('Matches:', len(res))
    pl = re.findall(r'placement', res, re.IGNORECASE)
    print(pl[:10])
except Exception as e:
    print('Failed:', e)
