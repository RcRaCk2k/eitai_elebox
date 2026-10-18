"""Constants for the EITAI ELEBOX-HV integration."""

DOMAIN = "eitai_elebox"
TOPIC_ROOT = "eitai_elebox"
CONF_DEVICE_ID = "device_id"
MANUFACTURER = "EITAI"
MODEL = "ELEBOX-HV"

SIGNAL_INFO = f"{DOMAIN}_info_{{}}"
SIGNAL_STATE = f"{DOMAIN}_state_{{}}"
SIGNAL_AVAILABILITY = f"{DOMAIN}_availability_{{}}"
SUPPORTED_SCHEMA = 1  # MQTT payload format, see docs/mqtt-format.md
