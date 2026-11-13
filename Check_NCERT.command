#!/bin/bash
# Double-click on a Mac: checks that every NCERT PDF the app needs can be downloaded from ncert.nic.in and is
# the same version the team tested. Writes the result to ~/Downloads/ncert_check.txt. Changes nothing in the repo.
cd "$(dirname "$0")" || exit 1
OUT="$HOME/Downloads/ncert_check.txt"
TMP="$(mktemp -d)"
{
  echo "NCERT download check, $(date)"
  python3 - "$TMP" <<'PY'
import re, sys, hashlib, urllib.request, pathlib
src = open("scripts/fetch_ncert.py", encoding="utf-8").read()
ns = {}
exec(compile(src.split("def sha256")[0], "fetch_ncert", "exec"), ns)
tmp = pathlib.Path(sys.argv[1])
for name, (url, expected) in ns["SOURCES"].items():
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        body = urllib.request.urlopen(req, timeout=120).read()
        ok_pdf = body.startswith(b"%PDF")
        same = hashlib.sha256(body).hexdigest() == expected
        print(("SAME    " if same else ("DIFFERS " if ok_pdf else "NOT PDF ")) + name + "  <- " + url + f"  ({len(body)} bytes)")
    except Exception as e:
        print("FAILED  " + name + "  <- " + url + f"  ({type(e).__name__}: {e})")
PY
} > "$OUT" 2>&1
rm -rf "$TMP"
cat "$OUT"
echo
echo "Saved to $OUT. You can close this window."
