# Publication synchronization

The verified source is [Lixing Tan's Google Scholar profile](https://scholar.google.com/citations?user=wtordYAAAAAJ). The synchronizer checks both the name and the verified `buaa.edu.cn` domain before using any rows.

## Triggers and publication

- Every push to `main` runs the sync check, including homepage text, layout, images, or internship pages. There is no path filter. Push-triggered runs use `--daily`: if a successful Scholar refresh already exists for the same Beijing calendar day (Asia/Shanghai, midnight boundary), they reuse the saved papers without any Scholar profile or detail requests. A failed or partial attempt does not count as a successful refresh; without a success that day, the next push can retry.
- A scheduled run starts on the 1st and 16th at 03:17 UTC (11:17 Beijing time). GitHub may delay scheduled runs.
- `Actions → Sync publications and deploy site → Run workflow` provides an immediate manual check.
- Local edits are checked when pushed; uncommitted files cannot trigger a GitHub workflow.

The 1st/16th scheduled runs and manual Run workflow checks still request Scholar. A success from either also counts toward that day's push deduplication. Skipping Scholar does not skip acceptance-news generation, venue sorting, project-video discovery, or the site build/deployment. The workflow's existing concurrency queue and latest-main checkout ensure queued pushes read the previous run's committed checkpoint.

`scholar_sync.json` records `status: skipped` and the reason when reusing today's successful refresh. `last_check` records the workflow check time; `last_attempt` and `last_success` retain the actual Scholar request and success times. A skipped run exits successfully and does not pretend a new Scholar fetch occurred.

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

## Acceptance news and venue ordering

`_data/news.json` supplies both language versions. Confirmed new publications and preprints promoted to a formal Journal/Conference/Book venue generate one acceptance announcement per paper. The English template is `Our paper <short title> was accepted to <venue>!`; the Chinese page uses the equivalent wording. Every acceptance announcement has one celebration icon and a link to its paper. The four newest announcements remain visible; older entries appear under More updates.

`short_title` can be edited per paper (e.g. STRIDE or CT2X-GAN). Otherwise the script uses a short title prefix or a shortened descriptive title, never an invented acronym. `news_venue` optionally overrides the venue label. `acceptance_date` accepts YYYY-MM or YYYY-MM-DD. Without an explicit acceptance date, News uses the month of detection in Beijing time, marked as an announcement month in the date tooltip; a publication date is never converted into an acceptance date.

`_data/news_state.json` tracks already known publications, preventing duplicate news on later metadata updates, retries, or scheduled runs. Existing ACM MM and BIBM acceptance news were migrated. The other already-published record was initialized as historical, so enabling the feature does not announce old publications as newly accepted. A manually accepted paper can generate news before Scholar catches up when its local venue explicitly says Accepted / 录用 or it has an `acceptance_date`.

Published papers are sorted by CCF A → B → C → SCI/JCR Q1 → Q2 → Q3 → Q4 → unlisted/unverified, then by descending year. Preprints retain their chronological order. `_data/venue_rankings.json` contains the 681 rows extracted from the CCF 2026 seventh-edition directory, with the official announcement, original-document mirror, page numbers and PDF checksum. Venue matching avoids treating a longer, unrelated conference name as a known conference or confusing conference and journal acronyms. Findings, workshops and companion publications do not inherit the main conference's rank. An explicit `paper_type: short` also excludes a conference paper from the CCF rank.

JCR is not supplied by Scholar. Only verified SCIE entries in `_data/jcr_rankings.json` (or a paper's `jcr` field) are used. Each entry needs `name`, optional `aliases`, `indexes` containing `SCIE`, the integer metric `year`, `source`, `verified_on`, and `categories` with category names and `quartile` values Q1–Q4. If several verified years exist, use the latest; for several subject categories, use the best quartile. ESCI-only records do not qualify as SCI. The registry currently contains no journals because the current publication list consists of conference papers. Unknown venues are placed last and listed in `scholar_sync.json` under `unranked_venues`; this does not assert they are not SCI-indexed. A future journal needs a verified JCR record before receiving a quartile rank.

Use `python3 scripts/sync_publications.py --presentation-only` to rebuild ordering and news after local editorial changes without requesting Scholar. The regular workflow does this even if Scholar is temporarily inaccessible.

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

## Project video previews

The same push / 1st-and-16th workflow runs `scripts/sync_project_videos.py` after Scholar synchronization, including when Scholar is inaccessible. It checks each paper's Project link for explicitly labelled overview, method, teaser or presentation videos, resolves relative URLs, and verifies MP4/WebM media types. HTML video/source tags and literal `methodVideo` / `overviewVideo` / `teaserVideo` / `presentationVideo` configurations are supported without executing remote scripts. Ordinary demo clips, ambiguous choices and iframe-only players are not automatically selected. Other dynamically generated players may need a future detector or an editorial mapping. No video files are copied into this repository.

`_data/project_videos.json` stores the discovered source and project URL; `_data/project_video_sync.json` records checks and warnings. A failed request preserves a previously verified source for the same project. A successful check with no supported video removes its preview. The browser retains the thumbnail on playback failure.

Desktop previews begin after a short hover, play muted inline, and stop on pointer exit, scrolling away, filtering, opening the image or hiding the tab. Mobile users and visitors with reduced-motion preferences use the explicit preview button. Video URLs are assigned only on interaction; the image remains visible until playback starts, with no change in the figure's dimensions. Only one preview plays at a time. Clicking the image continues to open its existing image lightbox.
