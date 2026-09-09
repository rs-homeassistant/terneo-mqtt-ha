"""Terneo MQTT Integration."""
import logging

_LOGGER = logging.getLogger(__name__)

DOMAIN = "terneo_mqtt"

async def async_setup(hass, config):
    """Set up terneo_mqtt from configuration.yaml."""
    return True
