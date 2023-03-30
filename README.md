# Carbon Intensity Forecast Tracking

Tracking differences between the UK National Grid's Carbon Intensity forecast and its eventual recorded value.

The UK's National Grid Electricity System Operator (NGESO) publishes [an API](https://carbon-intensity.github.io/api-definitions/#carbon-intensity-api-v2-0-0) showing half-hourly carbon intensity (gCO2/kWh) in different GB regions, together with a 48-hour forecast. The national data is based upon real and estimated metered generation statistics and values describing the relative carbon intensity of different energy sources (how much CO2 is released when generating the electricity). Regional data is based upon forecasted generation, consumption, and a complex model describing inter-region interaction.

Forecasts are updated every half hour, but the API does not keep historical forecasts. How reliable are they?

![Published CI values](./data/ci_lines.png)

## Basic idea

- Use GitHub Actions to [git scrape](https://simonwillison.net/2020/Oct/9/git-scraping/) the National Grid Carbon Intensity API. This method was inspired by [food-scraper](https://github.com/codeinthehole/food-scraper).
- Scraping occurs twice per hour on a [cron schedule](https://github.com/nmpowell/carbon-intensity-forecast-tracking/blob/main/.github/workflows/scrape_data.yaml) ([docs](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)).
- Download JSON data from the [various endpoints](https://carbon-intensity.github.io/api-definitions/#intensity), and save to `data/`.
- Once per day, data is converted to CSV, summarised, and plots are generated.
- It is then parsed into a Pandas dataframe for plotting and analysis.
- With summary statistics and plots, we can attempt to estimate the accuracy of the forecasts.

The plots in this README.md are updated daily from
To follow the plot generation, see the `notebook.ipynb`.
To run yourself, see **Usage** below.

## Forecast Accuracy

- For each actual 30-minute period defined by its "from" datetime, capture published forecasts for that period.
- Forecasts are published up to 48 hours ahead, so we should expect about 96 future forecasts for one real period, and 48 more from the "past" 24 hours.
- Also capture the "actual" values by choosing a stable point about 6 hours after the window has passed.
- We can do this for each of the published regions and the National data.


## Limitations

- Because Github's Actions runners are shared (and free), the cron isn't 100% reliable. We can expect some occasional missing data.

- Unclear what the difference between the 18th DNO region, "GB", and the "National" forecasts are. National: https://api.carbonintensity.org.uk/intensity/2023-03-11T22:31Z. Regional: https://api.carbonintensity.org.uk/regional/intensity/2023-03-11T22:31Z/fw48h at timepoint 0, regionid 18. Slightly different.

### Actual intensity and generation mix

To measure regional forecast accuracy it would be preferable to have a retrospective `actual` CI value for each region, but the API does not seem to provide this except at the national level: https://api.carbonintensity.org.uk/intensity for the previous complete half-hour window; https://api.carbonintensity.org.uk/intensity/2023-03-11T12:01Z for a specific window; https://api.carbonintensity.org.uk/intensity/2023-03-11T12:01Z/fw24h for that window and the next 48 hours' worth (etc.).

From tracking the `pt24h` data, it seems these "actual" values, as well as forecasts, can change slightly after the fact, i.e. after the relevant time window has passed.

although they do seem to settle down after a while

I've attempted to track this, as well, to give a good anchor against which we can measure forecast accuracy. For the purposes of this project, let us say the "final forecast" is the one accessible 6 hours after the start of the time window. So if we're measuring the accuracy of a half-hour window beginning 2023-03-11T12:00Z, we'll use the "final forecast" and "actual" intensity values from 2023-03-11T18:00Z.

## Prior work

I am unsure whether this has been done before. NGESO do not seem to release historic forecasts or figures about their accuracy.

Kate Rose Morley [created the canonincal great design](https://grid.iamkate.com/) for tracking the UK's carbon intensity.

If you know more, please let me know!

## Data

You can plot something similar using the datasets here: https://data.nationalgrideso.com/data-groups/carbon-intensity1: go to "Regional Carbon Intensity Forecast" (or "National"); click "Explore", choose "Chart", deselect "datetime" and add the regions. The "National" dataset includes the "actual" CI, so you can plot forecast alongside "actual". This is also shown here: https://carbonintensity.org.uk/#graphs

A forecast is published every 30 minutes for 48 hours ahead. How accurate are those numbers? How much do they change with each new forecast?

- A point in time at the start of a real window: 202303091630 or a UTC datetime
    - the number of half-hours preceding: 1-96, or -96 to -1

Estimating storage:

- intensity is an int
- generation perc is a float

- ~96 forecasts
- 1 actual value
- so intensity approx: 20 * 100 = 2000 measurements per real half-hour window. 4 bytes each so 8 kb.
- 48 half-hours per day, so * 50 = 100,000 measurements per day, 4 bytes each so 400 kb.
- 1 year so 150 MB per year
- Github size limit of about 5GB we should be fine for a while.

#### Dates and times

Throughout, I represent the 30-minute time window defined by a "from" and "to" timestamp in the API using just the "from" datetime. Thus a forecasted datetime given here represents a 30-minute window beginning at that time.

All times are UTC.

If we query the 48h forecast API at a given time X, the earliest time window (the 0th entry in the data) begins at the current time rounded down to the nearest half hour, i.e. "from" timepoint 0 represents the window covering the time requested.

#### Regions

- 17 DNO regions including national: https://carbon-intensity.github.io/api-definitions/#region-list and in the 48 hour forecasts, there's an 18th region which is "GB", which approximates the "national" forecast.

### Check this concept works at all

- Right now: https://api.carbonintensity.org.uk/regional/intensity/2023-03-09T20:01Z/fw48h

### API and data notes

- The national data and forecasts are different from the regional (national != GB).

- This will give you the CI and forecast for the current period: https://api.carbonintensity.org.uk/intensity
- Datetimes given to https://api.carbonintensity.org.uk/intensity/ ...
    1. with `{from}` like https://api.carbonintensity.org.uk/intensity/2023-03-10T16:00Z
    2. with `{from}/{to}` like https://api.carbonintensity.org.uk/intensity/2023-03-10T16:00Z/2023-03-10T16:59Z
    ... are all floored to give data from the _prior_ 30 minute window, so the syntax is up to _and including_ the `:00` and `:30` timestamps. (1) will give the window `(2023-03-10T15:30Z, 2023-03-10T16:00Z]`. (2) will give two results, with the window `(2023-03-10T15:30Z, 2023-03-10T16:30Z]`. If you request +1 minute, `2023-03-10T16:01Z`, you'll get the "expected" window. Seconds are ignored.
- This endpoint includes a `forecast` alongside the `actual` CI value. This forecast appears to be the last forecast for that datetime. The 95-odd prior forecasts are unavailable (hence, this project to scrape them).
- Regional forecast data does not appear to exist before https://api.carbonintensity.org.uk/regional/intensity/2018-05-10T23:30Z/fw48h

- They seem to have saved forecasts historically. The earliet seems to be "2018-05-10T23:30Z"
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

## Usage

### Install

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


### Run

1. Activate the venv: `source venv/bin/activate`
2. Download a JSON file. Examples:
    - 48-hour forward forecast from the current window: `python3 run.py download --output_dir "data" --now` (default endpoint)
    - 24-hour past "forecasts" from the current window: `python3 run.py download --output_dir "data" --now --endpoint regional_pt24h`
    - national intensity for a given date: `python run.py download --start_date "2023-03-13T12:01Z" -n 1 --endpoint national --unique_names`

Download JSON files for individual regions: `python run.py download_regional -o data --start_date "2023-03-13T12:01Z" -n 1 --endpoint one_region_fw48h`

To enable GitHub Actions, within the repo `Settings > Actions > General > Workflow permissions > Read and write permissions`.

Output JSON files are named for the `{from}` time given: `data/<endpoint>/<from-datetime>.json`.

3. Parse the data and produce CSV files. Example:
    - `python3 run.py wrangle --input_directory "data/national_fw48h" --output_dir "test"`

## Data storage

The JSON format isn't great for parsing and plotting, and the files are huge. So here they're wrangled (`wrangle.py`) into CSV.

1. From the JSON we have downloaded, get the "from" timestamps.


"The carbon intensity of electricity is a measure of how much CO2 emissions are produced per kilowatt hour of electricity consumed." Units, including forecast values, are usually gCO2/kWh.

Datetimes are all in UTC, in the format 2018-09-17T23:00:00


### Number of forecasts

- 48 * 2 = 96, plus the 0th so 97.
- I think some data is published more than 48 hours in advance. I wonder when values stop being updated?

Q: when do the forecasts _stop_ getting updated?
A: look at data/2023-03-10T1200Z.json. At position 0, this has:
    "from": "2023-03-10T11:30Z",
    "to": "2023-03-10T12:00Z",

- I might need to add 1 minute to the inspect datetime before querying the endpoint (done).

- It looks as though you can look a little further ahead than 48 hours - let's not worry about that too much.

- I've disabled the "latest" schedule and added a "t-3hr" schedule which starts the download at now() minus 3 hours. This should give us 5-6 timepoints after the forecasted time, recorded/downloaded 5-6 times, so we can see whether they ever change.


## Plots

- Want to find the final, settled value, so we can compare with forecasted values.

- Want to show forecasts forward from a given date. It doesn't matter if we collect some past dates if we know which to ignore. If we take the datetime at which we call the API as timepoint 0, it doesn't really matter if the values change after we've stopped looking at past values. The purpose is to discover the reliability 


Note that there could be many contributing factors to a broad error range, including missing data (not scraped successfully by this project).

This plot shows all the forecasted intensity values for a given half-hour window starting at the time indicated by the vertical dashed line at t=0. Forecasts are published half-hourly at the `fw48h` endpoint, up to 48 hours before a window, and 24 hours after, at the `pt24h` endpoint. Therefore we have up to 96 forecasts (left of the dashed line) and 48 post-hoc "forecasts" (right). Forecast and "actual" values are published post-hoc.

This box plot shows the the spread of percentage error for all intensity forecasts for 12 hours prior to the given time. The error is based upon the final recorded "actual" intensity value (i.e. `actual - forecast`).

This box plot shows the the spread of percentage error for all intensity forecasts for the past 7 days.

This box plot shows the spread of all the intensity forecasts (their actual intensity values) for 12 hours prior to the given time.

Because solar and wind generation data are estimates, their values can change even post-hoc (i.e. after the time window has passed). This can be seen from the orange line in <the plot>, tracking the `pt24h` endpoint, which varies slightly over time. Therefore, I compare forecast accuracy against the last available "actual" value, which is at most 24h after the window. (Instead of the last forecast value, which is fixed, or the first available "actual" value, which is recorded just after the window has passed.)

## TODOs & future work

- Summaries and plots for each region and DNO region
- track regions' performance i.e. lower CI
- investigate BMRS data: actual? total? https://www.bmreports.com/bmrs/?q=help/about-us

- Tests
    - saving valid json and csv
    - summary generation is idempotent

- summary measures:
    - for a given half-hour window, in a given region, with a known actual CI:
        - the spread: variance (or mean deviation) about a central point (the actual value; not the mean), stdev, interquartile range -- of the ~96 forecasts.

- make Github actions more efficient by reusing some steps

## Testing

Run `make test` or `pytest -v tests`
