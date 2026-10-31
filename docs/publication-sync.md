# Publication synchronization

The verified source is [Lixing Tan's Google Scholar profile](https://scholar.google.com/citations?user=wtordYAAAAAJ). The synchronizer checks both the name and the verified `buaa.edu.cn` domain before using any rows.

## Triggers and publication

- Every push to `main` runs the sync, including homepage text, layout, images, or internship pages. There is no path filter.
- A scheduled run starts on the 1st and 16th at 03:17 UTC (11:17 Beijing time). GitHub may delay scheduled runs.
- `Actions → Sync publications and deploy site → Run workflow` provides an immediate manual check.
- Local edits are checked when pushed; uncommitted files cannot trigger a GitHub workflow.

The same workflow synchronizes, commits the data with `GITHUB_TOKEN`, builds Jekyll, and deploys Pages. Bot commits do not recursively trigger another run. GitHub Pages must use **GitHub Actions** as its publishing source. The workflow rebases on concurrent edits and never force-pushes.

## Editorial data

`_data/publications.json` is shared by the English and Chinese pages. Edit it to change paper information; the two profile includes now use `paper-list.html`.

- `scholar` stores the last successfully observed row; it is not displayed verbatim.
- `locked_fields` protects manually curated fields from source changes. Existing titles, author lists, project links, images, summaries, and topics are protected.
- Author `marks` stores `*`, `†`, and `‡`. These remain intact when other metadata changes. When editing an automatically added author list, add `authors` to `locked_fields` to protect spelling and order too.
- `venue` and `summary` contain `en` / `zh` strings. Author names and paper titles remain in their publication language.
- A newly detected paper gets its complete authors and venue from the detail page, a source link, and the existing blank figure placeholder. The sync does not invent summaries, author roles, acceptance dates, or images.
- Papers are matched by Scholar citation ID, arXiv ID, or normalized title/aliases. Changed titles can be connected through the stable Scholar ID.
- Confirmed preprints move to Publications when Scholar reports a published venue. Already accepted/published records are never downgraded to arXiv. The manually accepted GSMedQA entry remains even while absent from Scholar.
- Missing papers are not automatically deleted. Add a former title to `aliases` when manually renaming a paper before it has been matched.

## Access failures

Google Scholar is a public HTML source, not an official API, and may block automated access. The script makes low-frequency requests with a timeout and no login, CAPTCHA bypass, or proxy rotation. A blocked page, invalid identity, empty response, truncated metadata, or repeated pagination is not treated as a successful empty list.

On failure, existing records remain. `_data/scholar_sync.json` distinguishes `last_attempt` from `last_success`, reports failed/partial status, and lists warnings. The workflow still deploys homepage edits, then reports failure so an access issue is visible in Actions. Unavailable individual records are retried on the next run. Do not claim a successful paper refresh when this status is failed/partial.

The status checkpoint is committed on each run, including scheduled checks with no new papers. GitHub may disable schedules in public repositories after prolonged inactivity; check the workflow's enabled state if updates stop. No external service credentials are required by this implementation.

## Local checks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/sync_publications.py
```

The first command is offline. The second reads the live public profile and updates the catalogue/status files. Review and push those files to publish the changes.
