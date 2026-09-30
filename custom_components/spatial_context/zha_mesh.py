"""ZHA network topology, read from ZHA's in-memory neighbor tables.

ZHA (zigpy) scans every router's neighbor table on its own schedule and keeps
the result on the gateway — the same data its built-in Visualization draws
and the `zha/devices` websocket returns. So unlike Z2M's `raw` networkmap
there is no over-the-air round trip unless a refresh is forced.

Output is converted to the shape of Z2M's `raw` networkmap links so
zigbee_mesh.py's merge/LQI-scaling applies unchanged.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

ZHA_DOMAIN = "zha"

# zigpy's Neighbor.RelationShip names -> the Zigbee spec values Z2M reports
# (0 = parent, 1 = child, 2 = sibling, 3 = none, 4 = previous child).
_RELATIONSHIP = {
    "Parent": 0,
    "Child": 1,
    "Sibling": 2,
    "NoneOfTheAbove": 3,
    "PreviousChild": 4,
}


def zha_available(hass: HomeAssistant) -> bool:
    """True when a ZHA config entry is loaded."""
    return any(
        entry.state is ConfigEntryState.LOADED
        for entry in hass.config_entries.async_entries(ZHA_DOMAIN)
    )


def convert_devices(
    devices: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """ZHA `zha_device_info` dicts -> (nodes, Z2M-`raw`-shaped links).

    Each neighbor-table entry becomes a link whose `targetIeeeAddr` is the
    router that reported it and `sourceIeeeAddr` the neighbor — matching
    Z2M's convention, which `_merge_links` relies on to attribute LQI to
    its reporter. Pure: no HA access, so it is unit-testable.
    """
    nodes = [
        {
            "ieee": device["ieee"],
            "friendly_name": device.get("user_given_name") or device.get("name") or device["ieee"],
            "type": device.get("device_type"),
        }
        for device in devices
    ]
    links = []
    for device in devices:
        for neighbor in device.get("neighbors", []):
            lqi = neighbor.get("lqi")
            links.append(
                {
                    "sourceIeeeAddr": neighbor["ieee"],
                    "targetIeeeAddr": device["ieee"],
                    "lqi": int(lqi) if lqi not in (None, "") else None,
                    "relationship": _RELATIONSHIP.get(neighbor.get("relationship")),
                }
            )
    return nodes, links


async def async_scan(hass: HomeAssistant, timeout: float) -> None:
    """Rescan every router's neighbor table over the air. Shielded so a
    timeout stops the wait without cancelling zigpy's scan half-way."""
    from homeassistant.components.zha.helpers import get_zha_gateway_proxy

    topology = get_zha_gateway_proxy(hass).gateway.application_controller.topology
    await asyncio.wait_for(asyncio.shield(topology.scan()), timeout=timeout)


def read(
    hass: HomeAssistant,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """ZHA's current topology from memory: (nodes, raw links, ieee -> HA
    device_id). No radio traffic. Imports ZHA lazily so this integration
    still loads on a Z2M-only install."""
    from homeassistant.components.zha.helpers import get_zha_gateway_proxy

    proxy = get_zha_gateway_proxy(hass)
    device_registry = dr.async_get(hass)
    devices = []
    ieee_to_device_id: dict[str, str] = {}
    for device_proxy in proxy.device_proxies.values():
        info = device_proxy.zha_device_info
        # zha_device_info's `name` is manufacturer + model; prefer the name
        # the user gave the device in HA.
        reg = device_registry.async_get(device_proxy.device_id)
        if reg is not None:
            info = {**info, "user_given_name": reg.name_by_user or reg.name}
            ieee_to_device_id[info["ieee"]] = device_proxy.device_id
        devices.append(info)

    nodes, links = convert_devices(devices)
    return nodes, links, ieee_to_device_id
