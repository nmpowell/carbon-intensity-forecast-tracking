# TODOs

- [ ] summary files are too big and impractical
- [ ] concat forecasting CSVs into daily files
- [ ] when plotting, dates in plots are 1h off due to timezoning
- [ ] factor out scipy entirely; use numpy
- [ ] split summaries into smaller files, or only generate for a small date range, or on the fly.
- [ ] Summaries and plots for each region and DNO region
- [ ] track regions' performance i.e. lower CI
- [ ] investigate BMRS data: actual? total? https://www.bmreports.com/bmrs/?q=help/about-us
- [ ] make Github actions more efficient by reusing some steps
- [ ] fix: {"asctime": "2023-04-11 02:21:50,229", "levelname": "INFO", "name": "matplotlib.font_manager", "message": "Failed to extract font properties from /usr/share/fonts/truetype/noto/NotoColorEmoji.ttf: In FT2Font: Can not load face (unknown file format; error code 0x2)"}
- Could overwrite a single file per endpoint, and use a tool like [git-history](https://simonwillison.net/2021/Dec/7/git-history/) to retrieve past data. Keeping the files separate is a little more transparent, though, and a bit easier for now.

- Tests
    - [ ] saving valid json and csv
    - [ ] summary generation is idempotent