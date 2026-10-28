import urllib.request
import re
req = urllib.request.Request('https://www.op.gg/summoners/eune/Soshi-2609', headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8')
matches1 = re.findall(r'<img[^>]+src=[^>]+profileIcon(\d+)\.(?:jpg|png)', html, re.IGNORECASE)
print('Matches 1:', matches1)
matches2 = re.findall(r'"profile_icon_id":\s*(\d+)', html)
print('Matches 2:', matches2)
matches3 = re.findall(r'profileicon/(\d+)\.png', html, re.IGNORECASE)
print('Matches 3:', matches3)
matches4 = re.findall(r'profileicon/(\d+)\.jpg', html, re.IGNORECASE)
print('Matches 4:', matches4)
matches5 = re.findall(r'(\d+)\.png', html, re.IGNORECASE)
print('Matches 5:', [m for m in matches5 if len(m) > 2])
