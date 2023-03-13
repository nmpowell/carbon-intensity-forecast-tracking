# API constants

BASE_URL = "https://api.carbonintensity.org.uk"
TEMPLATE_48HR_FORWARD_URL = BASE_URL + "/regional/intensity/{}/fw48h"
TEMPLATE_48HR_PAST_URL = BASE_URL + "/regional/intensity/{}/pt24h"
TEMPLATE_48HR_REGION_FORWARD_URL = BASE_URL + "/regional/intensity/{}/fw48h/regionid/{}"
TEMPLATE_48HR_REGION_PAST_URL = BASE_URL + "/regional/intensity/{}/pt24h/regionid/{}"
TEMPLATE_NATIONAL_URL = BASE_URL + "/intensity/{}"
TEMPLATE_NATIONAL_FORWARD_URL = BASE_URL + "/intensity/{}/fw48h"
TEMPLATE_NATIONAL_PAST_URL = BASE_URL + "/intensity/{}/pt24h"

TEMPLATE_URLS = {
    "regional_fw48h": TEMPLATE_48HR_FORWARD_URL,
    "regional_pt24h": TEMPLATE_48HR_PAST_URL,
    "one_region_fw48h": TEMPLATE_48HR_REGION_FORWARD_URL,
    "one_region_pt24h": TEMPLATE_48HR_REGION_PAST_URL,
    "national": TEMPLATE_NATIONAL_URL,
    "national_fw48h": TEMPLATE_NATIONAL_FORWARD_URL,
    "national_pt24h": TEMPLATE_NATIONAL_PAST_URL,
}

REGION_IDS = range(1, 18 + 1)

DATETIME_FMT_STR = "%Y-%m-%dT%H:%MZ"
