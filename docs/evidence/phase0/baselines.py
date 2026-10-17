import json, os, re, sys, time, urllib.parse, urllib.request
key = os.environ.get("NCBI_API_KEY", "")
truth = ["GSE36892", "GSE35469"]
def get(url, data=None):
    req = urllib.request.Request(url, data=data.encode() if data else None)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)
def geo(term):
    q = {"db": "gds", "term": term, "retmax": 500, "retmode": "json"}
    if key: q["api_key"] = key
    r = get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(q))["esearchresult"]
    ids = r["idlist"]; acc = []
    for i in range(0, len(ids), 200):
        body = urllib.parse.urlencode({"db": "gds", "retmode": "json", "id": ",".join(ids[i:i+200]), **({"api_key": key} if key else {})})
        s = get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", body)["result"]
        acc += [s[u]["accession"] for u in s["uids"]]
        time.sleep(0.4)
    gse = [a for a in acc if a.startswith("GSE")]
    return r["count"], gse
def omicsdi(term):
    d = get("https://www.omicsdi.org/ws/dataset/search?" + urllib.parse.urlencode({"query": term, "size": 100}))
    acc = [re.sub(r"^E-GEOD-", "GSE", x.get("id", "")) for x in d.get("datasets", [])]
    return d.get("count"), acc
plain = "I need matched RNA-seq and Ribo-seq data from human or mouse cells before and after mTOR inhibition (for example Torin1, rapamycin or INK128) to measure changes in translation efficiency"
for name, fn in [("GEO", geo), ("OmicsDI", omicsdi)]:
    for term in [plain, "mTOR ribosome profiling", "Torin1 ribosome profiling RNA-seq"]:
        try:
            n, acc = fn(term)
        except Exception as e:
            print(f"{name} [{term[:50]}] ERROR {e}"); continue
        ranks = {t: (acc.index(t) + 1 if t in acc else None) for t in truth}
        print(f"{name:7} [{term[:60]}] total={n} returned={len(acc)} ranks={ranks} top5={acc[:5]}")
