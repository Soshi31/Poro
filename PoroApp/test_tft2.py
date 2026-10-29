import urllib.request, re
req = urllib.request.Request('https://tft.op.gg/summoners/eune/Soshi-2609', headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
html = urllib.request.urlopen(req).read().decode('utf-8')
print("NEXT_DATA in html:", "__NEXT_DATA__" in html)
print("Games in html:", "games" in html)
matches = re.findall(r'"placement":(\d)', html)
print("Placements found:", matches[:10])
matches2 = re.findall(r'"rank":(\d)', html)
print("Ranks found:", matches2[:10])
