"""ZHA topology -> the mesh shape the panel draws.

Device dicts mirror ZHA's `zha_device_info` (what the `zha/devices`
websocket returns): neighbor `lqi` is a string and `relationship` a zigpy
enum name.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.spatial_context.zha_mesh import convert_devices  # noqa: E402
from custom_components.spatial_context.zigbee_mesh import _merge_links  # noqa: E402

COORD = "00:11:22:ff:fe:00:00:01"
ROUTER = "00:11:22:ff:fe:00:00:02"
REMOTE = "00:11:22:ff:fe:00:00:03"


def _neighbor(ieee, relationship, lqi, device_type="Router"):
    return {
        "device_type": device_type,
        "rx_on_when_idle": "On",
        "relationship": relationship,
        "extended_pan_id": "aa:bb:cc:dd:ee:ff:00:11",
        "ieee": ieee,
        "nwk": "0x1234",
        "permit_joining": "Unknown",
        "depth": "1",
        "lqi": str(lqi),
    }


DEVICES = [
    {
        "ieee": COORD,
        "name": "Example Coordinator",
        "device_type": "Coordinator",
        "neighbors": [_neighbor(ROUTER, "Sibling", 80)],
    },
    {
        "ieee": ROUTER,
        "name": "Acme Bulb A19",
        "user_given_name": "Porch Light",
        "device_type": "Router",
        "neighbors": [
            _neighbor(COORD, "Sibling", 90, "Coordinator"),
            _neighbor(REMOTE, "Child", 120, "EndDevice"),
        ],
    },
    # A sleepy end device keeps no neighbor table.
    {"ieee": REMOTE, "name": "Acme Remote", "device_type": "EndDevice", "neighbors": []},
]


def test_nodes_prefer_the_user_given_name():
    nodes, _ = convert_devices(DEVICES)
    by_ieee = {n["ieee"]: n for n in nodes}
    assert by_ieee[ROUTER]["friendly_name"] == "Porch Light"
    assert by_ieee[REMOTE]["friendly_name"] == "Acme Remote"
    assert by_ieee[COORD]["type"] == "Coordinator"


def test_links_are_attributed_to_the_reporting_router():
    _, links = convert_devices(DEVICES)
    child = next(link for link in links if link["sourceIeeeAddr"] == REMOTE)
    assert child == {
        "sourceIeeeAddr": REMOTE,
        "targetIeeeAddr": ROUTER,
        "lqi": 120,
        "relationship": 1,
    }


def test_merged_mesh_marks_the_remote_parent_and_merges_both_directions():
    _, links = convert_devices(DEVICES)
    merged = {frozenset((m["source_ieee"], m["target_ieee"])): m for m in _merge_links(links)}
    assert len(merged) == 2

    parent = merged[frozenset((ROUTER, REMOTE))]
    assert parent["parent_child"] is True
    assert parent["lqi_readings"] == [120]

    backbone = merged[frozenset((COORD, ROUTER))]
    assert backbone["parent_child"] is False
    assert backbone["lqi_readings"] == [90, 80]


def test_missing_lqi_and_unknown_relationship_are_tolerated():
    devices = [
        {
            "ieee": ROUTER,
            "device_type": "Router",
            "neighbors": [{**_neighbor(REMOTE, "Undefined", 0), "lqi": ""}],
        }
    ]
    _, links = convert_devices(devices)
    assert links[0]["lqi"] is None
    assert links[0]["relationship"] is None
