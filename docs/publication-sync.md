# Publication synchronization

The source is [Lixing Tan's arXiv author feed](https://arxiv.org/a/tan_l_3.atom), configured in `_data/arxiv_author.json`. The synchronizer verifies the author identifier, name and ORCID before merging papers. It uses the author `.atom` endpoint with separate author names, not name search or Google Scholar. Google Scholar scraping and its workflow checkpoint have been removed. Historical `scholar` metadata in existing records is retained as provenance only and is never used for synchronization.

New papers must be associated with this arXiv author identifier to appear in its feed; see [arXiv's author identifier documentation](https://info.arxiv.org/help/author_identifiers.html). At migration, the feed contains seven papers. FlashGaze is absent from the feed and remains in the local catalogue, alongside other manually maintained publications. `not_in_author_feed` reports known arXiv IDs absent from the current feed without deleting them.

## Triggers and publication

- Every push to `main` checks synchronization, without path filters. Push runs use `--daily`: a successful fetch from the same Beijing calendar day (Asia/Shanghai, midnight boundary) is reused. Failed/partial attempts do not create a success checkpoint; a later push can retry.
- Scheduled checks run on the 1st and 16th at 03:17 UTC (11:17 Beijing time). GitHub may delay scheduled runs.
- `Actions → Sync arXiv publications and deploy site → Run workflow` forces an immediate fetch. Scheduled checks also fetch regardless of the daily cache.
- Local edits take effect after they are pushed.

Skipping the feed fetch does not skip acceptance-news generation, venue sorting, missing thumbnail/project-link discovery, project-video discovery, or deployment. `_data/arxiv_sync.json` records `status: skipped` when reusing a successful fetch. `last_check` records the current check; `last_attempt` and `last_success` retain actual request/success times.

The workflow synchronizes and commits data/assets with `GITHUB_TOKEN`, then builds Jekyll and deploys Pages in the same run. Bot commits do not recursively trigger another workflow. GitHub Pages must use **GitHub Actions** as its publishing source. Runs are queued, check out the latest `main`, and rebase concurrent edits without force-pushing. No external credentials are needed. GitHub may disable schedules in public repositories after prolonged inactivity; check the workflow's enabled state if updates stop.

## Editorial data

`_data/publications.json` supplies both language pages through `paper-list.html`.

- `arxiv` stores observed metadata, version, original submission date, update date, full authors, journal reference and DOI. The versionless arXiv ID is the primary match; title/aliases are a fallback. Ambiguous matches are reported without adding duplicates.
- `locked_fields` protects title, authors, year, venue and publication section when merging metadata. Existing images, summaries, links and topics are preserved. The separate asset script can fill missing images or append a missing Project/Code link even if `image`/`links` is locked, but never replaces an existing selection.
- Author `marks` (`*`, `†`, `‡`) survive updates. Lock `authors` to preserve manually adjusted spelling/order. The script does not invent author roles, summaries or acceptance dates.
- New records get complete authors, a Paper link, original submission month and basic topic tags. Preprints sort by first submission, not the most recent revision. A v2 update merges into the same record.
- Only an explicit arXiv `journal_ref` indicating a published venue can promote a preprint. A DOI alone, submission comment or arXiv release does not establish acceptance. Existing accepted/published records are never downgraded.
- Papers absent from the feed are retained. Empty/wrong-author/malformed feeds do not clear the catalogue. Older source versions do not replace newer metadata.

## Automatic thumbnails and project links

`scripts/sync_paper_assets.py` runs after metadata synchronization and before video discovery, including when the daily metadata fetch is skipped.

For missing project/code links, it scans the versioned arXiv HTML for explicit labels such as “Project page” or “Code available.” It excludes navigation, footer and bibliography links, fetches candidates and checks the page title/heading against the paper's title or acronym. It only adds an unambiguous verified link. It does not construct a URL from a guessed repository name. Existing links remain untouched. Inaccessible candidates are recorded for retry; verified title mismatches are recorded under `rejected_links`; absence of a discovered link is not proof that no project page exists.

For missing thumbnails, it considers captioned figures, preferring framework/overview/architecture/pipeline diagrams and penalizing ablations, comparison plots and individual panels. Logos, tables and very small images are excluded. The best readable candidate is converted to a local WebP, preserving aspect ratio, with a maximum size of 1200 × 900. If HTML has no usable figure, a PDF first-page preview is rendered and labelled as such. This is heuristic selection; a manually chosen replacement can always be supplied in `publications.json`.

Images are stored in `assets/img/papers/arxiv-<id>.webp`. `_data/paper_assets.json` records each scan's version, source URL, figure caption/ID, chosen link evidence, image provenance and warnings. `_data/paper_asset_sync.json` records the latest run. Existing hand-selected assets in `assets/img/papers/sources.json` are unchanged.

Complete image/project entries need no additional scan. Successful scans that find no advertised project are cached for seven days; a new arXiv version or a missing local image file causes an earlier recheck. Failed scans remain retryable. arXiv resource requests are spaced at least three seconds apart, with timeouts and size limits. Media/link failures preserve existing content and are reported as warnings without preventing deployment.

## Acceptance news and venue ordering

`_data/news.json` supplies both language versions. Confirmed new publications and preprints promoted to a formal Journal/Conference/Book venue generate one acceptance announcement per paper. The English template is `Our paper <short title> was accepted to <venue>!`; the Chinese page uses the equivalent wording. Every acceptance announcement has one celebration icon and a link to its paper. The four newest announcements remain visible; older entries appear under More updates.

`short_title` can be edited per paper (e.g. STRIDE or CT2X-GAN). Otherwise the script uses a short title prefix or a shortened descriptive title, never an invented acronym. `news_venue` optionally overrides the venue label. `acceptance_date` accepts YYYY-MM or YYYY-MM-DD. Without an explicit acceptance date, News uses the month of detection in Beijing time, marked as an announcement month in the date tooltip; a publication date is never converted into an acceptance date.

`_data/news_state.json` tracks already known publications, preventing duplicate news on later metadata updates, retries, or scheduled runs. Existing ACM MM and BIBM acceptance news were migrated. The other already-published record was initialized as historical, so enabling the feature does not announce old publications as newly accepted. A manually accepted paper can generate news before arXiv metadata is updated when its local venue explicitly says Accepted / 录用 or it has an `acceptance_date`.

Published papers are sorted by CCF A → B → C → SCI/JCR Q1 → Q2 → Q3 → Q4 → unlisted/unverified, then by descending year. Preprints retain their chronological order. `_data/venue_rankings.json` contains the 681 rows extracted from the CCF 2026 seventh-edition directory, with the official announcement, original-document mirror, page numbers and PDF checksum. Venue matching avoids treating a longer, unrelated conference name as a known conference or confusing conference and journal acronyms. Findings, workshops and companion publications do not inherit the main conference's rank. An explicit `paper_type: short` also excludes a conference paper from the CCF rank.

JCR is not supplied by arXiv. Only verified SCIE entries in `_data/jcr_rankings.json` (or a paper's `jcr` field) are used. Each entry needs `name`, optional `aliases`, `indexes` containing `SCIE`, the integer metric `year`, `source`, `verified_on`, and `categories` with category names and `quartile` values Q1–Q4. If several verified years exist, use the latest; for several subject categories, use the best quartile. ESCI-only records do not qualify as SCI. The registry currently contains no journals because the current publication list consists of conference papers. Unknown venues are retained in the catalogue and listed in `arxiv_sync.json` under `unranked_venues`; this does not assert they are not SCI-indexed. A future journal needs a verified JCR record before receiving a quartile rank.

Use `python3 scripts/sync_publications.py --presentation-only` to rebuild ordering and news after local editorial changes without requesting arXiv. The regular workflow does this even if arXiv is temporarily inaccessible.

## Access failures

A failed author request, invalid identity, empty feed or incomplete snapshot retains existing records. Individual malformed entries produce a partial result while other verified entries remain usable. `_data/arxiv_sync.json` distinguishes `last_attempt` and `last_success` and lists warnings. The workflow publishes preserved records and other homepage edits, then reports metadata-sync failure visibly in Actions. Do not describe failed/partial metadata checks as successful refreshes.

## Local checks

```sh
python3 -m venv /tmp/homepage-sync-venv
. /tmp/homepage-sync-venv/bin/activate
python -m pip install -r requirements-sync.txt
python -m unittest discover -s tests -v
python scripts/sync_publications.py
python scripts/sync_paper_assets.py
python scripts/sync_project_videos.py
```

Tests are offline and cover feed identity/merge failures, editorial preservation, daily caching, figure/link selection, PDF fallback and existing video discovery. The final three commands access public sources and update local data/assets. Review and push the result to publish it.

## Project video previews

The same push / 1st-and-16th workflow runs `scripts/sync_project_videos.py` after arXiv synchronization and thumbnail/project-link discovery, including when arXiv is inaccessible. It checks each paper's Project link for explicitly labelled overview, method, teaser or presentation videos, resolves relative URLs, and verifies MP4/WebM media types. HTML video/source tags and literal `methodVideo` / `overviewVideo` / `teaserVideo` / `presentationVideo` configurations are supported without executing remote scripts. Ordinary demo clips, ambiguous choices and iframe-only players are not automatically selected. Other dynamically generated players may need a future detector or an editorial mapping. No video files are copied into this repository.

`_data/project_videos.json` stores the discovered source and project URL; `_data/project_video_sync.json` records checks and warnings. A failed request preserves a previously verified source for the same project. A successful check with no supported video removes its preview. The browser retains the thumbnail on playback failure.

Desktop previews begin after a short hover, play muted inline, and stop on pointer exit, scrolling away, filtering, opening the image or hiding the tab. Mobile users and visitors with reduced-motion preferences use the explicit preview button. Video URLs are assigned only on interaction; the image remains visible until playback starts, with no change in the figure's dimensions. Only one preview plays at a time. Clicking the image continues to open its existing image lightbox.

## Homepage publication eligibility

Published & Accepted displays only verified CCF venues or verified SCIE journals, using the derived `show_on_homepage` field. Preprints are unaffected. Unlisted or unverified published papers remain in the catalogue but are omitted from both language pages and topic-filter counts. A verified SCIE journal may be shown even before its JCR quartile is supplied; it sorts after quartile-ranked journals. Later verification automatically restores a hidden record. News remains independent; acceptance links for hidden papers point to the external paper link rather than a missing homepage anchor. This presentation rule is recomputed even when the daily arXiv fetch is skipped.
