"""
Module 6: HA Critical Process Crash Tests

Verifies HA behavior when critical processes crash on DPUs in the
t1-smartswitch-ha topology.

For each process crash case there are 4 variations:
    1. Crash on active DPU,  traffic landing on active DPU
    2. Crash on active DPU,  traffic landing on standby DPU
    3. Crash on standby DPU, traffic landing on active DPU
    4. Crash on standby DPU, traffic landing on standby DPU

Expected Control Plane : HA state converges eventually.
Expected Data Plane    : T2 receives packets with allowed disruption.

Traffic uses PrivateLink (PL) DASH config as defined in PR #22161.
"""

import json
import logging
import time
import ptf.packet as scapy
import ptf.testutils as testutils
import pytest
from ptf.mask import Mask

from tests.common.utilities import wait_until
from tests.common.ha.smartswitch_ha_gnmi_utils import apply_messages
from tests.ha.ha_utils import wait_for_ha_state
from tests.ha.configs.privatelink_config import (
    APPLIANCE_VIP,
    VM1_PA,
    VM1_CA,
    PE_CA,
    PE_PA,
    ENI_MAC,
    VNET1_VNI,
    ENCAP_VNI,
    PL_CONFIG_TABLES,
)

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.topology("t1-smartswitch-ha"),
]

###############################################################################
# Constants
###############################################################################

PROCESS_RECOVERY_TIMEOUT = 120  # seconds to wait for process to recover
HA_CONVERGENCE_TIMEOUT = 180    # seconds to wait for HA state to converge
HA_CHECK_INTERVAL = 5           # polling interval in seconds
TRAFFIC_DISRUPTION_SECS = 30   # allowed disruption window in seconds
PL_VERIFY_TIMEOUT = 10          # seconds to wait for PL packet at receiver

ACTIVE_SCOPE_KEY = "vdpu0_0:haset0_0"
STANDBY_SCOPE_KEY = "vdpu1_0:haset0_0"

# Keys used in pl_traffic_config dict
_LOCAL_PTF_INTF = "local_ptf_intf"
_LOCAL_PTF_MAC = "local_ptf_mac"
_REMOTE_PTF_RECV = "remote_ptf_recv_intf"
_DUT_MAC = "dut_mac"

###############################################################################
# Helpers
###############################################################################


def kill_process_on_dpu(duthost, dpu_index, process_name):
    """
    Kill a named process inside the DPU container.

    Args:
        duthost      : DUT host object
        dpu_index    : DPU index (0-based)
        process_name : Process name to kill (e.g. "syncd")
    """
    container = f"dash-hadpu{dpu_index}"
    cmd = f"docker exec {container} pkill -9 {process_name} || true"
    logger.info(f"{duthost.hostname}: killing '{process_name}' on {container}")
    duthost.shell(cmd)


def wait_for_process_recovery(duthost, dpu_index, process_name, timeout=PROCESS_RECOVERY_TIMEOUT):
    """
    Wait until the process is running again inside the DPU container.

    Args:
        duthost      : DUT host object
        dpu_index    : DPU index (0-based)
        process_name : Process name to check
        timeout      : Maximum wait time in seconds

    Returns:
        bool: True if process recovered, False on timeout
    """
    container = f"dash-hadpu{dpu_index}"

    def _is_running():
        result = duthost.shell(
            f"docker exec {container} pgrep {process_name} || true"
        )
        return bool(result["stdout"].strip())

    logger.info(f"{duthost.hostname}: waiting for '{process_name}' recovery on {container}")
    return wait_until(timeout, HA_CHECK_INTERVAL, 0, _is_running)


def verify_ha_state_converged(duthost, scope_key, expected_state):
    """
    Assert that the HA scope reaches the expected state within timeout.

    Args:
        duthost        : DUT host object
        scope_key      : HA scope key (e.g. "vdpu0_0:haset0_0")
        expected_state : Expected HA state string ("active" or "standby")
    """
    assert wait_for_ha_state(
        duthost,
        scope_key=scope_key,
        expected_state=expected_state,
        timeout=HA_CONVERGENCE_TIMEOUT,
        interval=HA_CHECK_INTERVAL,
    ), (
        f"{duthost.hostname}: HA scope '{scope_key}' did not reach "
        f"'{expected_state}' within {HA_CONVERGENCE_TIMEOUT}s"
    )
    logger.info(f"{duthost.hostname}: HA scope '{scope_key}' reached '{expected_state}'")


def _build_outbound_pl_packet(pl_config):
    """
    Build an outbound PrivateLink packet (VM -> DPU -> PE direction).

    Outer: VxLAN encap with ip_src=VM1_PA, ip_dst=APPLIANCE_VIP,
           vni=VNET1_VNI.
    Inner: UDP packet ip_src=VM1_CA, ip_dst=PE_CA, eth_src=ENI_MAC.

    Args:
        pl_config : dict with _LOCAL_PTF_MAC and _DUT_MAC keys

    Returns:
        scapy packet to send
    """
    inner = testutils.simple_udp_packet(
        eth_src=ENI_MAC,
        eth_dst="ff:ff:ff:ff:ff:ff",
        ip_src=VM1_CA,
        ip_dst=PE_CA,
    )
    outer = testutils.simple_vxlan_packet(
        eth_src=pl_config[_LOCAL_PTF_MAC],
        eth_dst=pl_config[_DUT_MAC],
        ip_src=VM1_PA,
        ip_dst=APPLIANCE_VIP,
        with_udp_chksum=False,
        vxlan_vni=int(VNET1_VNI),
        inner_frame=inner,
    )
    return outer


def _build_expected_pl_packet():
    """
    Build a mask for the expected PL output packet at T2 (PE side).

    Expected: outer GRE/NVGRE with ip_src=APPLIANCE_VIP, ip_dst=PE_PA.
    The mask ignores inner payload and Ethernet fields so verification
    is tolerant of exact DUT/PE MACs.

    Returns:
        ptf.mask.Mask matching the outer GRE envelope
    """
    exp_pkt = testutils.simple_gre_packet(
        ip_src=APPLIANCE_VIP,
        ip_dst=PE_PA,
        gre_key_present=True,
        gre_key=int(ENCAP_VNI) << 8,
    )
    masked = Mask(exp_pkt)
    masked.set_do_not_care_scapy(scapy.Ether, "src")
    masked.set_do_not_care_scapy(scapy.Ether, "dst")
    masked.set_do_not_care_scapy(scapy.IP, "ttl")
    masked.set_do_not_care_scapy(scapy.IP, "chksum")
    masked.set_do_not_care_scapy(scapy.GRE, "seqnum_present")
    masked.set_do_not_care_scapy(scapy.GRE, "seqnum")
    return masked


def verify_pl_traffic(ptfadapter, pl_config, timeout=PL_VERIFY_TIMEOUT):
    """
    Send one outbound PL packet (VM -> DPU -> PE) and verify it exits at T2.

    Follows the same pattern as test_ha_steady_state_pl.py from PR #22161:
      1. Flush dataplane
      2. Send VxLAN-encapped DASH packet from the T0/VM-side PTF port
      3. Verify a GRE-encapped packet arrives on any T2/PE-side PTF port

    Args:
        ptfadapter : PTF adapter fixture
        pl_config  : dict from pl_traffic_config fixture
        timeout    : seconds to wait for packet at T2
    """
    send_pkt = _build_outbound_pl_packet(pl_config)
    exp_pkt = _build_expected_pl_packet()

    ptfadapter.dataplane.flush()
    logger.info(
        f"Sending PL outbound packet on PTF port {pl_config[_LOCAL_PTF_INTF]}"
    )
    testutils.send(ptfadapter, pl_config[_LOCAL_PTF_INTF], send_pkt, count=1)
    testutils.verify_packet_any_port(
        ptfadapter,
        exp_pkt,
        pl_config[_REMOTE_PTF_RECV],
        timeout=timeout,
    )
    logger.info("PL outbound packet received at T2 — dataplane verified")


###############################################################################
# Fixtures
###############################################################################


@pytest.fixture(scope="module")
def active_dut(duthosts):
    """Return the DUT that hosts the active DPU (DUT index 0)."""
    return duthosts[0]


@pytest.fixture(scope="module")
def standby_dut(duthosts):
    """Return the DUT that hosts the standby DPU (DUT index 1)."""
    return duthosts[1]


@pytest.fixture(scope="module")
def pl_traffic_config(duthosts, tbinfo):
    """
    Collect PTF interface indices and MACs needed to send/receive PL packets.

    For each DUT, queries minigraph facts to find:
      - local_ptf_intf  : PTF port index connected to a T0 (VM/leaf) neighbor
      - local_ptf_mac   : MAC learned by DUT from that T0 neighbor
      - remote_ptf_recv : list of PTF port indices connected to T2 (spine) neighbors
      - dut_mac         : DUT Ethernet MAC address

    Returns:
        list of per-DUT config dicts (index matches duthosts index)
    """
    configs = []
    for duthost in duthosts:
        mg_facts = duthost.get_extended_minigraph_facts(tbinfo)
        config_facts = duthost.get_running_config_facts()
        arp_table = duthost.switch_arptable()["ansible_facts"]["arptable"].get("v4", {})

        dut_mac = config_facts["DEVICE_METADATA"]["localhost"]["mac"]

        local_ptf_intf = None
        local_ptf_mac = None
        remote_ptf_recv = []

        bgp_neighbors = config_facts.get("BGP_NEIGHBOR", {})

        for interface, neighbor in mg_facts["minigraph_neighbors"].items():
            neigh_name = neighbor.get("name", "")
            port_id = mg_facts["minigraph_ptf_indices"].get(interface)
            if port_id is None:
                continue

            if "T0" in neigh_name and local_ptf_intf is None:
                local_ptf_intf = port_id
                # Find PTF MAC from DUT ARP table for this neighbor's IP
                for neigh_ip, bgp_cfg in bgp_neighbors.items():
                    if bgp_cfg.get("name") == neigh_name and neigh_ip in arp_table:
                        local_ptf_mac = arp_table[neigh_ip].get("macaddress")
                        break

            elif "T2" in neigh_name:
                remote_ptf_recv.append(port_id)

        configs.append({
            _LOCAL_PTF_INTF: local_ptf_intf,
            _LOCAL_PTF_MAC:  local_ptf_mac,
            _REMOTE_PTF_RECV: remote_ptf_recv,
            _DUT_MAC:        dut_mac,
        })

    return configs


@pytest.fixture(scope="module")
def setup_pl_config(duthosts, ptfhost, localhost, setup_ha_config):
    """
    Push PrivateLink DASH tables to DPU0 on both DUTs via gnmi.

    Uses PL_CONFIG_TABLES from tests/ha/configs/privatelink_config.py,
    following the pattern established in PR #22161.

    Yields after config is applied; cleans up on teardown.
    """
    pl_config = {}
    for table in PL_CONFIG_TABLES:
        pl_config.update(table)

    tmp_file = "/tmp/ha_pl_config.json"

    for duthost in duthosts:
        logger.info(f"Pushing PL config to {duthost.hostname} DPU0")
        duthost.copy(
            content=json.dumps(pl_config, indent=4),
            dest=tmp_file
        )
        apply_messages(
            localhost=localhost,
            duthost=duthost,
            ptfhost=ptfhost,
            messages=pl_config,
            dpu_index=0,
            setup_ha_config=setup_ha_config,
            gnmi_key="DASH_APPLIANCE_TABLE",
            filename=tmp_file,
            set_db=True,
            wait_after_apply=5,
        )
        logger.info(f"PL config applied on {duthost.hostname}")

    yield

    # Teardown: remove PL config from both DUTs
    for duthost in duthosts:
        logger.info(f"Removing PL config from {duthost.hostname} DPU0")
        apply_messages(
            localhost=localhost,
            duthost=duthost,
            ptfhost=ptfhost,
            messages=pl_config,
            dpu_index=0,
            setup_ha_config=setup_ha_config,
            gnmi_key="DASH_APPLIANCE_TABLE",
            filename=tmp_file,
            set_db=False,
        )


###############################################################################
# Test Class — syncd crash
###############################################################################


class TestSyncdCrash:
    """
    Verify HA behavior when syncd crashes on a DPU.

    PL traffic (VM -> PE via PrivateLink routing) is used for data-plane
    verification, following PR #22161 (test_ha_steady_state_pl.py pattern):
      - ptfadapter sends a VxLAN-encapped DASH packet from the T0/VM side
      - verify a GRE-encapped packet arrives at T2/PE side

    4 variations:
        test_syncd_crash_active_dpu_traffic_on_active   (variation 1)
        test_syncd_crash_active_dpu_traffic_on_standby  (variation 2)
        test_syncd_crash_standby_dpu_traffic_on_active  (variation 3)
        test_syncd_crash_standby_dpu_traffic_on_standby (variation 4)
    """

    def _run_syncd_crash(
        self,
        crash_duthost,
        crash_dpu_index,
        crash_scope_key,
        expected_ha_state_after_crash,
        verify_duthost,
        verify_scope_key,
        expected_ha_state_verify,
        ptfadapter,
        pl_config,
    ):
        """
        Common test body for syncd crash scenarios.

        Steps:
            1. Verify PL dataplane is functional (pre-crash baseline)
            2. Kill syncd on target DPU
            3. Verify HA state converges on crash DUT
            4. Verify HA state unchanged on peer DUT
            5. Wait for allowed disruption window; re-verify PL traffic
            6. Wait for syncd to recover
        """
        logger.info(
            f"=== syncd crash on {crash_duthost.hostname} "
            f"DPU{crash_dpu_index} (scope: {crash_scope_key}) ==="
        )

        # Step 1: Verify PL traffic is flowing (pre-crash baseline)
        logger.info("Step 1: Verify PL dataplane pre-crash")
        verify_pl_traffic(ptfadapter, pl_config)

        # Step 2: Kill syncd
        logger.info("Step 2: Kill syncd on DPU")
        kill_process_on_dpu(crash_duthost, crash_dpu_index, "syncd")

        # Step 3: Verify HA state on the crashed DUT converges
        logger.info("Step 3: Verify HA state converges on crash DUT")
        verify_ha_state_converged(
            crash_duthost, crash_scope_key, expected_ha_state_after_crash
        )

        # Step 4: Verify HA state on the peer DUT is unchanged
        logger.info("Step 4: Verify HA state is unchanged on peer DUT")
        verify_ha_state_converged(
            verify_duthost, verify_scope_key, expected_ha_state_verify
        )

        # Step 5: Allow disruption window then re-verify PL traffic
        logger.info(
            f"Step 5: Wait {TRAFFIC_DISRUPTION_SECS}s disruption window, "
            "then re-verify PL traffic"
        )
        time.sleep(TRAFFIC_DISRUPTION_SECS)
        verify_pl_traffic(ptfadapter, pl_config)
        logger.info("PL traffic re-verified after HA convergence")

        # Step 6: Wait for syncd to recover
        logger.info("Step 6: Wait for syncd recovery")
        recovered = wait_for_process_recovery(crash_duthost, crash_dpu_index, "syncd")
        assert recovered, (
            f"syncd did not recover on {crash_duthost.hostname} "
            f"DPU{crash_dpu_index} within {PROCESS_RECOVERY_TIMEOUT}s"
        )
        logger.info("syncd recovered successfully")

    # ------------------------------------------------------------------
    # Variation 1: Crash on active DPU, traffic landing on active DPU
    # ------------------------------------------------------------------
    def test_syncd_crash_active_dpu_traffic_on_active(
        self,
        active_dut,
        standby_dut,
        setup_ha_config,
        setup_pl_config,
        activate_dash_ha_from_json,
        ptfadapter,
        pl_traffic_config,
    ):
        """
        Variation 1: syncd crash on active DPU, traffic landing on active DPU.

        Expected:
            Control Plane : HA state converges eventually.
            Data Plane    : T2 receives PL packets with allowed disruption.
        """
        self._run_syncd_crash(
            crash_duthost=active_dut,
            crash_dpu_index=0,
            crash_scope_key=ACTIVE_SCOPE_KEY,
            expected_ha_state_after_crash="active",
            verify_duthost=standby_dut,
            verify_scope_key=STANDBY_SCOPE_KEY,
            expected_ha_state_verify="standby",
            ptfadapter=ptfadapter,
            pl_config=pl_traffic_config[0],
        )

    # ------------------------------------------------------------------
    # Variation 2: Crash on active DPU, traffic landing on standby DPU
    # ------------------------------------------------------------------
    def test_syncd_crash_active_dpu_traffic_on_standby(
        self,
        active_dut,
        standby_dut,
        setup_ha_config,
        setup_pl_config,
        activate_dash_ha_from_json,
        ptfadapter,
        pl_traffic_config,
    ):
        """
        Variation 2: syncd crash on active DPU, traffic landing on standby DPU.

        Expected:
            Control Plane : HA state converges eventually.
            Data Plane    : T2 receives PL packets with allowed disruption.
        """
        self._run_syncd_crash(
            crash_duthost=active_dut,
            crash_dpu_index=0,
            crash_scope_key=ACTIVE_SCOPE_KEY,
            expected_ha_state_after_crash="active",
            verify_duthost=standby_dut,
            verify_scope_key=STANDBY_SCOPE_KEY,
            expected_ha_state_verify="standby",
            ptfadapter=ptfadapter,
            pl_config=pl_traffic_config[1],
        )

    # ------------------------------------------------------------------
    # Variation 3: Crash on standby DPU, traffic landing on active DPU
    # ------------------------------------------------------------------
    def test_syncd_crash_standby_dpu_traffic_on_active(
        self,
        active_dut,
        standby_dut,
        setup_ha_config,
        setup_pl_config,
        activate_dash_ha_from_json,
        ptfadapter,
        pl_traffic_config,
    ):
        """
        Variation 3: syncd crash on standby DPU, traffic landing on active DPU.

        Expected:
            Control Plane : HA state remains unchanged.
            Data Plane    : T2 receives PL packets with allowed disruption.
        """
        self._run_syncd_crash(
            crash_duthost=standby_dut,
            crash_dpu_index=0,
            crash_scope_key=STANDBY_SCOPE_KEY,
            expected_ha_state_after_crash="standby",
            verify_duthost=active_dut,
            verify_scope_key=ACTIVE_SCOPE_KEY,
            expected_ha_state_verify="active",
            ptfadapter=ptfadapter,
            pl_config=pl_traffic_config[0],
        )

    # ------------------------------------------------------------------
    # Variation 4: Crash on standby DPU, traffic landing on standby DPU
    # ------------------------------------------------------------------
    def test_syncd_crash_standby_dpu_traffic_on_standby(
        self,
        active_dut,
        standby_dut,
        setup_ha_config,
        setup_pl_config,
        activate_dash_ha_from_json,
        ptfadapter,
        pl_traffic_config,
    ):
        """
        Variation 4: syncd crash on standby DPU, traffic landing on standby DPU.

        Expected:
            Control Plane : HA state remains unchanged.
            Data Plane    : T2 receives PL packets with allowed disruption.
        """
        self._run_syncd_crash(
            crash_duthost=standby_dut,
            crash_dpu_index=0,
            crash_scope_key=STANDBY_SCOPE_KEY,
            expected_ha_state_after_crash="standby",
            verify_duthost=active_dut,
            verify_scope_key=ACTIVE_SCOPE_KEY,
            expected_ha_state_verify="active",
            ptfadapter=ptfadapter,
            pl_config=pl_traffic_config[1],
        )
