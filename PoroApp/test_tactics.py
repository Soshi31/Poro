import urllib.request, re, json
req = urllib.request.Request('https://tactics.tools/player/eune/Soshi/2609', headers={'User-Agent': 'Mozilla/5.0'})
res = urllib.request.urlopen(req).read().decode('utf-8')
match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', res)
if match:
    json_str = match.group(1)

    # regex for match id and placement
    matches_block = re.search(r'"matches":\[(.*?)\]\s*,\s*"playerInfo"', json_str)
    if matches_block:
        block = matches_block.group(1)
        # find all id and placements
        # 'id':'EUN1_123'
        results = re.findall(r'"id":"([^"]+)","info":\{.*?"placement":(\d)', block)
        print("Regex results:", results[:5])
