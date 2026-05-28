import re

path = "plugins/wazuh_overview/main.py"
data = open(path, "rb").read()
text = data.decode("utf-8")
lines = text.split("\n")

out = []
out.append("bytes=%d lines=%d" % (len(data), len(lines)))
out.append("has_null=%s" % (b"\x00" in data))
for needle in ("donut", "vuln_chart", "cvss", "Severity breakdown",
               "matplotlib", ".pie(", "Vulnerabilities", "_build_vuln",
               "_draw_vuln", "No vulnerabilities"):
    out.append("count[%s]=%d" % (needle, text.count(needle)))

# Real line numbers of any def whose name contains 'vuln' or 'chart' or 'donut'
out.append("--- defs ---")
for i, ln in enumerate(lines, 1):
    m = re.match(r"\s*def (\w+)", ln)
    if m and any(k in m.group(1).lower() for k in ("vuln", "chart", "donut", "cvss")):
        out.append("%d:%s" % (i, m.group(1)))

open("_diag_out.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("done, wrote _diag_out.txt with", len(out), "lines")
