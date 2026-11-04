"""Constants for the Hot Spring integration."""

from datetime import timedelta
import logging

from hotspring import HeatingMode

DOMAIN = "hotspring"

LOGGER = logging.getLogger(__package__)
SCAN_INTERVAL = timedelta(seconds=60)

DEPRECATED_REMOVAL_VERSION = "2027.6.0"

HEATING_MODE_HEAT_SAVER = "heat_saver"
HEATING_MODE_HEAT_WITH_BOOST = "heat_with_boost"
HEATING_MODE_AUTO_SAVER = "auto_saver"
HEATING_MODE_AUTO_WITH_BOOST = "auto_with_boost"
HEATING_MODE_CHILL = "chill"

HEATING_MODE_TO_OPTION: dict[HeatingMode, str] = {
    HeatingMode.HEAT_SAVER: HEATING_MODE_HEAT_SAVER,
    HeatingMode.HEAT_WITH_BOOST: HEATING_MODE_HEAT_WITH_BOOST,
    HeatingMode.AUTO_SAVER: HEATING_MODE_AUTO_SAVER,
    HeatingMode.AUTO_WITH_BOOST: HEATING_MODE_AUTO_WITH_BOOST,
    HeatingMode.CHILL: HEATING_MODE_CHILL,
}

OPTION_TO_HEATING_MODE: dict[str, HeatingMode] = {
    option: mode for mode, option in HEATING_MODE_TO_OPTION.items()
}
