# One failed CI run, explained (L16 evidence)

The guide asks for "one failed CI run with an explanation". This is a real failure from the first CI runs of pull request #14 (branch `vidhya/r5-r6`), not a staged one.

## What failed

- Failed runs: https://github.com/jileshl/Socratic/actions/runs/41468473035 (push) and https://github.com/jileshl/Socratic/actions/runs/41468737613 (pull request), 2 Nov 2026
- Job and step: `eval-gate` → "Fetch NCERT chapters (not stored in the repo)". The `tests` and `docker` jobs passed.
- Output:

```
FAILED  ch9-Light–Reflection-and-Refraction.pdf from https://ncert.nic.in/textbook/pdf/jesc109.pdf: <urlopen error [Errno 104] Connection reset by peer>
FAILED  ch10-The-Human-Eye-and-the-Colourful-World .pdf from https://ncert.nic.in/textbook/pdf/jesc110.pdf: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1010)>
FAILED  ch11-Electricity.pdf from https://ncert.nic.in/textbook/pdf/jesc111.pdf: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1010)>
3 chapter PDF(s) missing.
```

## Why

The NCERT PDFs are deliberately not in the repository (the guide forbids redistributing them), so CI downloads them before it can build the retrieval index and run the Recall@5 gate. From GitHub's runners, ncert.nic.in reset one connection and served an incomplete certificate chain for the others. Browsers repair an incomplete chain by themselves; Python's HTTPS client does not. Because the index could not be built, the gate could not run, and the job failed. This was a failure of the CI setup, not of the tutor or the evaluation code.

What we did not do: turn off certificate checking, or commit the PDFs (or the index, which contains NCERT text) to make CI pass.

## Fix

- `scripts/fetch_ncert.py` now first downloads a zip of the three PDFs from the team's Google Drive (link in `config/ncert_zip_url.txt`, or the `NCERT_PDF_ZIP_URL` secret if one is set), then falls back to ncert.nic.in with retries and a browser-like User-Agent. The PDFs themselves stay out of the repository.
- Fix commits: `9a11709` (zip download) and [sha — TO FILL] (link file)
- Passing run after the fix: [link — TO FILL]

## What it shows

The gate depends on data the repository cannot contain. The fix keeps the gate real (it still fails below Recall@5 = 0.85) while respecting the no-redistribution rule.
