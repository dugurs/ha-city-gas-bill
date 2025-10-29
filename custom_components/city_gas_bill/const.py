# custom_components/city_gas_bill/const.py

"""Constants for the City Gas Bill integration."""
from logging import getLogger
from typing import Final

DOMAIN: Final = "city_gas_bill"
LOGGER = getLogger(__package__)

# Platforms
SENSOR: Final = "sensor"
NUMBER: Final = "number"
BUTTON: Final = "button"  # --- NEW ---
PLATFORMS: Final = [SENSOR, NUMBER, BUTTON]

# Configuration and options
CONF_PROVIDER: Final = "provider"
CONF_GAS_SENSOR: Final = "gas_sensor"
CONF_READING_DAY: Final = "reading_day"

# Defaults
DEFAULT_BASE_FEE: Final = 1250.0

# Data coordinator keys
DATA_PREV_MONTH_HEAT: Final = "prev_month_heat"
DATA_CURR_MONTH_HEAT: Final = "curr_month_heat"
DATA_PREV_MONTH_PRICE: Final = "prev_month_price"
DATA_CURR_MONTH_PRICE: Final = "curr_month_price"

# Attributes
ATTR_START_DATE: Final = "start_date"
ATTR_END_DATE: Final = "end_date"
ATTR_DAYS_TOTAL: Final = "total_days"
ATTR_DAYS_PREV_MONTH: Final = "prev_month_days"
ATTR_DAYS_CURR_MONTH: Final = "curr_month_days"

# Event for transferring bill data before reset
EVENT_BILL_RESET: Final = f"{DOMAIN}_bill_reset"