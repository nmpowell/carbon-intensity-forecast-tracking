# API URLs

BASE_URL = "https://api.carbonintensity.org.uk"
TEMPLATE_48HR_FORWARD_URL = BASE_URL + "/regional/intensity/{}/fw48h"
TEMPLATE_48HR_PAST_URL = BASE_URL + "/regional/intensity/{}/pt24h"
TEMPLATE_NATIONAL_URL = BASE_URL + "/intensity/{}"
TEMPLATE_NATIONAL_FORWARD_URL = BASE_URL + "/intensity/{}/fw48h"
TEMPLATE_NATIONAL_PAST_URL = BASE_URL + "/intensity/{}/pt24h"

TEMPLATE_URLS = {
    "regional_forward": TEMPLATE_48HR_FORWARD_URL,
    "regional_past": TEMPLATE_48HR_PAST_URL,
    "national": TEMPLATE_NATIONAL_URL,
    "national_forward": TEMPLATE_NATIONAL_FORWARD_URL,
    "national_past": TEMPLATE_NATIONAL_PAST_URL,
}
