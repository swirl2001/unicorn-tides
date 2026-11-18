# Unicorn Low Tide

Every upcoming Saturday-afternoon minus tide with daylight to explore the tide pools below the Ritz-Carlton, Half Moon Bay.

- **Unicorn:** Saturday low tide of −1.0 ft or lower (MLLW), at noon or later and at least 30 minutes before sunset. About once a year, nearly always November–February.
- **Almost unicorn:** same, at −0.75 ft or lower.

`forecast.py` pulls NOAA tide predictions for Pillar Point Harbor (station 9414131) four years ahead, works out sunrise and sunset for the reef, writes `site/data.json`, and emails a reminder 7 days before and the day before each qualifying Saturday. Standard library only.

GitHub Actions runs it every morning (`check.yml`) and publishes `site/` to GitHub Pages. `pages.yml` republishes when the page changes.

Secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD` (Google app password), `ALERT_EMAILS` (comma-separated, sent in BCC). Without them it prints the email instead.
