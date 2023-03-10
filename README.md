# Carbon Intensity Forecast Tracking

Tracking differences between the UK National Grid's Carbon Intensity forecast and its eventual recorded value.

The [API itself](https://carbon-intensity.github.io/api-definitions/#carbon-intensity-api-v2-0-0) does not seem to record or expose historical forecasts. We want to know: how reliable are they?

This repo uses GitHub Actions to do [git scraping](https://simonwillison.net/2020/Oct/9/git-scraping/) and is heavily inspired by [food-scraper](https://github.com/codeinthehole/food-scraper).

## Basic idea

- Git scrape the National Grid Carbon Intensity API ([repo](https://github.com/carbon-intensity)) on a half-hourly basis.
- Scraping is performed by Github Actions on a [cron schedule](https://github.com/nmpowell/carbon-intensity-forecast-tracking/blob/main/.github/workflows/run.yaml) twice per hour.
- Data is downloaded from the [regional forward-48hr endpoint](https://carbon-intensity.github.io/api-definitions/#get-regional-intensity-from-fw48h), saved to `data/` and, for now, is committed to this repo.
- Save the data to a local database or spreadsheet, committed to this repo.
- Show, for a given half-hour window in history:
    - the predicted CI at each of the ~96 half-hourly time points
    - the "actual" CI recorded
    - the error in these predictions at each of the ~96 preceding time points (+/-)
        - in CI units ("absolute error")
        - as a % of the actual CI ("proportional error")
    - (hopefully there is some convergence as the forecast improves and the present time approaches the window)
- For each region and DNO region that the National Grid

- Some summary measures:
    - for a given half-hour window, in a given region, with a known actual CI:
        - the spread: variance (or mean deviation) about a central point (the actual value; not the mean), stdev, interquartile range -- of the ~96 forecasts.
    - for a region:

Test cron 11, 41

1. Scrape the data.


## Data

- Because Github's Actions runners are shared (and free), the cron isn't 100% reliable and we can expect some occasional missing data.

- A point in time at the start of a real window: 202303091630 or a UTC datetime
    - the number of half-hours preceding: 1-96, or -96 to -1

Estimating storage:

- intensity is an int
- generation perc is a float

- 17 DNO regions including national: https://carbon-intensity.github.io/api-definitions/#region-list
- ~96 forecasts
- 1 actual value
- so intensity approx: 20 * 100 = 2000 measurements per real half-hour window. 4 bytes each so 8 kb.
- 48 half-hours per day, so * 50 = 100,000 measurements per day, 4 bytes each so 400 kb.
- 1 year so 150 MB per year
- Github size limit of about 5GB we should be fine for a while.

### Check this concept works at all

- Right now: https://api.carbonintensity.org.uk/regional/intensity/2023-03-09T20:01Z/fw48h

### Historical Data

- They seem to have saved forecasts historically. The earliest seems to be "2018-05-10T23:30Z"
- No need to scrape every half hour; we can scrape daily instead and just get the previous day's ~48 forecasts.
- _Actually_, that's wrong. They aren't publishing historical forecasts; it's just that you can lookup "forecasts" forwards and backwards from historical dates. Those forecasts I guess are the last ones they do for the date? They don't seem to change.
    - e.g. look at the last ones here: https://api.carbonintensity.org.uk/regional/intensity/2019-01-01T02:31Z/fw48h vs the earliest ones here: https://api.carbonintensity.org.uk/regional/intensity/2019-01-03T01:31Z/fw48h vs #46 here: https://api.carbonintensity.org.uk/regional/intensity/2019-01-02T02:31Z/fw48h - exactly the same!
- So you _do_ have to scrape every 30 minutes in order to not lose any data.

- You don't seem to be able to wrap dates around years, e.g. 31st December - 1st Jan. E.g. https://api.carbonintensity.org.uk/regional/intensity/2022-12-31T21:31Z/fw48h

- So you can query https://api.carbonintensity.org.uk/regional/intensity/2018-05-10T23:30Z/fw48h onwards in half-hourly increments and download the data.
- The JSON structure is: data: 0: the present window, time requested in the URL (`{from}`), floored to the nearest half hour.
    - (the exception is if you go under the earliest time, when the number of timepoints reduces but 0 is still 2018-05-10T23:30Z.)
    - so for 0 and 95 following half-hours, we have:
        - from: and to: values, UTC
        - regions: array of 18 regions, 0 - 17, 
    - data.1 is the 0-time + 30 minutes.
    - data.2 is the 1-time + 30 minutes, etc., into the future.
    - data.95 is the 0-time + 47.5 hours.

- (The "past" 24hr URL is a bit more confusing as https://api.carbonintensity.org.uk/regional/intensity/2018-05-11T01:30Z/pt24h gives you the past 24hrs but the _oldest_ one is still timepoint 0. The "to" field is then the floor of the timepoint you requested in the 47th entry (if it goes back that far - not for this example URL; it's index 3 in this one).)

## Install

1. Clone this repository `git clone git@github.com:nmpowell/carbon-intensity-forecast-tracking.git`
2. Set up a local virtual environment using Python 3.10+
    ``` sh
    cd carbon-intensity-forecast-tracking/
    python3 -m venv venv                 # use this subdirectory name to piggyback on .gitignore
    source venv/bin/activate
    ```

3. You can install the requirements in this virtual environment in a couple of ways:
    ``` sh
    python3 -m pip install --upgrade pip
    python3 -m pip install -r requirements.txt
    # or
    make install
    ```
    `make` will call `pip-sync` which will use the `requirements.txt` file to install requirements. To regenerate that file, use `pip-compile requirements.in`


## Usage

1. Activate the venv: `source venv/bin/activate`
2. Download a JSON file: `python3 run.py download --output_dir "data" --now`

To enable GitHub Actions, within the repo `Settings > Actions > General > Workflow permissions > Read and write permissions`.

## Storing

The JSON format isn't great for parsing and plotting values. Instead wrangle into a CSV.

1. From the JSON we have downloaded, get the "from" timestamps.
