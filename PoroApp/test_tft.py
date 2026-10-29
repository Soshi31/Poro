import urllib.request, re
req = urllib.request.Request('https://www.op.gg/summoners/eune/Soshi-2609', headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8')
print("op.gg profile_icon_id:", set(re.findall(r'"profile_icon_id":\s*(\d+)', html)))
print("op.gg profileIcon:", set(re.findall(r'profileicon(\d+)\.(?:jpg|png)', html, re.IGNORECASE)))
print("op.gg profile_icon/", set(re.findall(r'profile_icon/(\d+)\.(?:jpg|png)', html, re.IGNORECASE)))

req2 = urllib.request.Request('https://tft.op.gg/summoners/eune/Soshi-2609', headers={'User-Agent': 'Mozilla/5.0'})
html2 = urllib.request.urlopen(req2).read().decode('utf-8')
print("tft.op.gg profile_icon_url:", set(re.findall(r'profileIcon(\d+)\.(?:jpg|png)', html2, re.IGNORECASE)))
