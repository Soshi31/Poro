import subprocess

def run(cmd):
    return subprocess.check_output(cmd, text=True).strip()

throttled = run(["vcgencmd", "get_throttled"])
temp = run(["vcgencmd", "measure_temp"])

print("Temperatura:", temp)
print("Throttled:", throttled)

value = int(throttled.split("=")[1], 16)

flags = [
    (0, "UNDERVOLTAGE ACUM"),
    (1, "CPU frequency capped ACUM"),
    (2, "THROTTLING ACUM"),
    (3, "temperature limit ACUM"),

    (16, "undervoltage a aparut de la boot"),
    (17, "CPU frequency a fost limitata de la boot"),
    (18, "throttling a aparut de la boot"),
    (19, "temperature limit a aparut de la boot"),
]

problems = []

for bit, text in flags:
    if value & (1 << bit):
        problems.append(text)

if not problems:
    print("OK - alimentarea pare stabila.")
else:
    print("ATENTIE:")
    for problem in problems:
        print("-", problem)