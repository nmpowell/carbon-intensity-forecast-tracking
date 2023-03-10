# TODO: use jsonschema to validate the structure

import json
import os

import pandas as pd


from scrape.files import json_data_filepath


# Load JSON to a dict
def load_json_file(filepath: str) -> dict:
    with open(filepath) as f:
        return json.load(f)
    

def get_forecast_data_from_json_file(filepath: str) -> dict:
    return load_json_file(filepath).get("data")


def get_one_region_intensity_forecasts(data: dict, key: str = "regionid", value: int = 1) -> dict:        
    return {e.get("from"): e.get("regions")[0].get("intensity").get("forecast") for e in data}
    
    
def files_to_dataframe(input_directory: str) -> pd.DataFrame:
    # list files in the directory
    files = os.listdir(input_directory)
    subset = []
    for filepath in files:
        data = get_forecast_data_from_json_file(os.path.join(input_directory, filepath))
        results = get_one_region_intensity_forecasts(data)
        results["filename"] = os.path.basename(filepath)
        subset.append(results)
        
    df = pd.DataFrame(subset)
    # sort columns alphabetically
    df = df.reindex(sorted(df.columns), axis=1)
    # use "filename" as the index
    df.set_index("filename", inplace=True)
    # sort the index alphabetically
    df.sort_index(inplace=True)
    return df
    



# Load the JSON file, normalise, and return a pandas DataFrame
def load_normalise(filepath: str) -> pd.DataFrame:
with open(filepath) as f:
    data = json.load(f)
df = pd.json_normalize(data)

    df = load_json(filepath)
    df = normalise(df)
    return df


# Given a JSON filepath, load and return a pandas DataFrame
def load_json(filepath: str) -> pd.DataFrame:
    return pd.read_json(filepath, orient="records", lines=True)
