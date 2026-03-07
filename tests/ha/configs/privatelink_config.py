"""
PrivateLink DASH configuration constants for HA tests.

Based on PR #22161 (HA Steady Traffic Test with PL Config).
Uses JSON-serializable string values suitable for apply_messages / gnmi push.
"""

# ---------------------------------------------------------------------------
# IP / MAC addresses
# ---------------------------------------------------------------------------
APPLIANCE_VIP = "10.1.0.5"
VM1_PA = "25.1.1.1"          # VM host physical address
VM1_CA = "10.0.0.11"         # VM customer address
VM_CA_SUBNET = "10.0.0.0/16"
PE_PA = "101.1.2.3"          # Private endpoint physical address
PE_CA = "10.2.0.100"         # Private endpoint customer address
PE_CA_SUBNET = "10.2.0.0/16"

PL_ENCODING_IP = "::d107:64:ff71:0:0"
PL_ENCODING_MASK = "::ffff:ffff:ffff:0:0"
PL_OVERLAY_SIP = "fd41:108:20:abc:abc::0"
PL_OVERLAY_SIP_MASK = "ffff:ffff:ffff:ffff:ffff:ffff::"
PL_OVERLAY_DIP = "2603:10e1:100:2::3401:203"
PL_OVERLAY_DIP_MASK = "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"

VM_MAC = "44:E3:9F:EF:C4:6E"
ENI_MAC = "F4:93:9F:EF:C4:7E"

# ---------------------------------------------------------------------------
# IDs / VNIs
# ---------------------------------------------------------------------------
APPLIANCE_ID = "100"
LOCAL_REGION_ID = "100"
VM_VNI = "4321"
ENCAP_VNI = "100"
VNET1 = "Vnet1"
VNET1_VNI = "2001"
VNET1_GUID = "559c6ce8-26ab-4193-b946-ccc6e8f930b2"
ENI_ID = "497f23d7-f0ac-4c99-a98f-59b470e8c7bd"
ROUTE_GROUP1 = "RouteGroup1"
ROUTE_GROUP1_GUID = "48af6ce8-26cc-4293-bfa6-0126e8fcdeb2"
METER_POLICY_V4 = "MeterPolicyV4"

# ---------------------------------------------------------------------------
# DASH table configs  (JSON-serialisable — string enum values)
# ---------------------------------------------------------------------------

APPLIANCE_CONFIG = {
    f"DASH_APPLIANCE_TABLE:{APPLIANCE_ID}": {
        "sip": APPLIANCE_VIP,
        "vm_vni": VM_VNI,
        "local_region_id": LOCAL_REGION_ID,
        "trusted_vnis": [ENCAP_VNI, VM_VNI],
    }
}

VNET_CONFIG = {
    f"DASH_VNET_TABLE:{VNET1}": {
        "vni": VNET1_VNI,
        "guid": VNET1_GUID,
    }
}

ENI_CONFIG = {
    f"DASH_ENI_TABLE:{ENI_ID}": {
        "vnet": VNET1,
        "underlay_ip": VM1_PA,
        "mac_address": ENI_MAC,
        "eni_id": ENI_ID,
        "admin_state": "enabled",
        "pl_underlay_sip": APPLIANCE_VIP,
        "pl_sip_encoding": f"{PL_ENCODING_IP}/{PL_ENCODING_MASK}",
        "trusted_vnis": VM_VNI,
    }
}

ROUTING_TYPE_PL_CONFIG = {
    "DASH_ROUTING_TYPE_TABLE:privatelink": {
        "items": [
            {"action_name": "action1", "action_type": "4_to_6"},
            {
                "action_name": "action2",
                "action_type": "static_encap",
                "encap_type": "nvgre",
                "vni": ENCAP_VNI,
            },
        ]
    }
}

ROUTING_TYPE_VNET_CONFIG = {
    "DASH_ROUTING_TYPE_TABLE:vnet": {
        "items": [
            {"action_name": "action1", "action_type": "maprouting"},
        ]
    }
}

ROUTE_GROUP1_CONFIG = {
    f"DASH_ROUTE_GROUP_TABLE:{ROUTE_GROUP1}": {
        "guid": ROUTE_GROUP1_GUID,
        "version": "rg_version",
    }
}

ENI_ROUTE_GROUP1_CONFIG = {
    f"DASH_ENI_ROUTE_TABLE:{ENI_ID}": {
        "group_id": ROUTE_GROUP1,
    }
}

PE_SUBNET_ROUTE_CONFIG = {
    f"DASH_ROUTE_TABLE:{ROUTE_GROUP1}:{PE_CA_SUBNET}": {
        "routing_type": "vnet",
        "vnet": VNET1,
    }
}

VM_SUBNET_ROUTE_CONFIG = {
    f"DASH_ROUTE_TABLE:{ROUTE_GROUP1}:{VM_CA_SUBNET}": {
        "routing_type": "vnet",
        "vnet": VNET1,
    }
}

PE_VNET_MAPPING_CONFIG = {
    f"DASH_VNET_MAPPING_TABLE:{VNET1}:{PE_CA}": {
        "routing_type": "privatelink",
        "underlay_ip": PE_PA,
        "overlay_sip_prefix": f"{PL_OVERLAY_SIP}/{PL_OVERLAY_SIP_MASK}",
        "overlay_dip_prefix": f"{PL_OVERLAY_DIP}/{PL_OVERLAY_DIP_MASK}",
    }
}

VM_VNET_MAPPING_CONFIG = {
    f"DASH_VNET_MAPPING_TABLE:{VNET1}:{VM1_CA}": {
        "routing_type": "vnet",
        "underlay_ip": VM1_PA,
        "mac_address": VM_MAC,
    }
}

INBOUND_VNI_ROUTE_RULE_CONFIG = {
    f"DASH_ROUTE_RULE_TABLE:{ENI_ID}:{ENCAP_VNI}:{PE_PA}/32": {
        "action_type": "decap",
        "priority": "0",
    }
}

METER_POLICY_V4_CONFIG = {
    f"DASH_METER_POLICY_TABLE:{METER_POLICY_V4}": {
        "ip_version": "ipv4",
    }
}

METER_RULE1_V4_CONFIG = {
    f"DASH_METER_RULE_TABLE:{METER_POLICY_V4}:1": {
        "priority": "10",
        "ip_prefix": VM_CA_SUBNET,
        "metering_class": "512",
    }
}

METER_RULE2_V4_CONFIG = {
    f"DASH_METER_RULE_TABLE:{METER_POLICY_V4}:2": {
        "priority": "20",
        "ip_prefix": PE_CA_SUBNET,
        "metering_class": "520",
    }
}

# Ordered list of all PL configs to push to a DPU
PL_CONFIG_TABLES = [
    APPLIANCE_CONFIG,
    VNET_CONFIG,
    ROUTING_TYPE_PL_CONFIG,
    ROUTING_TYPE_VNET_CONFIG,
    ROUTE_GROUP1_CONFIG,
    ENI_CONFIG,
    ENI_ROUTE_GROUP1_CONFIG,
    PE_SUBNET_ROUTE_CONFIG,
    VM_SUBNET_ROUTE_CONFIG,
    PE_VNET_MAPPING_CONFIG,
    VM_VNET_MAPPING_CONFIG,
    INBOUND_VNI_ROUTE_RULE_CONFIG,
    METER_POLICY_V4_CONFIG,
    METER_RULE1_V4_CONFIG,
    METER_RULE2_V4_CONFIG,
]
