import urllib.request
try:
    req = urllib.request.Request('https://lolchess.gg/api/profile/eune/Soshi/2609', headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req).read().decode('utf-8')
    print("NO V1:", html[:100])
except Exception as e:
    print(e)
