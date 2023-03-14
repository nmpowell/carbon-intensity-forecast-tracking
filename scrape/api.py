# API constants

BASE_URL = "https://api.carbonintensity.org.uk"

TEMPLATE_URLS = {
    "regional_fw48h": BASE_URL + "/regional/intensity/{}/fw48h",
    "regional_pt24h": BASE_URL + "/regional/intensity/{}/pt24h",
    "one_region_fw48h": BASE_URL + "/regional/intensity/{}/fw48h/regionid/{}",
    "one_region_pt24h": BASE_URL + "/regional/intensity/{}/pt24h/regionid/{}",
    "national": BASE_URL + "/intensity/{}",
    "national_fw48h": BASE_URL + "/intensity/{}/fw48h",
    "national_pt24h": BASE_URL + "/intensity/{}/pt24h",
}

REGION_IDS = range(1, 18 + 1)

DATETIME_FMT_STR = "%Y-%m-%dT%H:%MZ"
