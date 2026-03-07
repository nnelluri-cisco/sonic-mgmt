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
"""

import logging
import pytest
import time

from tests.common.utilities import wait_until
from tests.ha.ha_utils import wait_for_ha_state

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

ACTIVE_SCOPE_KEY = "vdpu0_0:haset0_0"
STANDBY_SCOPE_KEY = "vdpu1_0:haset0_0"

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


def run_traffic_and_verify(ha_io, active_dut_index, disruption_secs=TRAFFIC_DISRUPTION_SECS):
    """
    Start traffic, wait for the disruption window, then verify T2 received packets.

    Args:
        ha_io            : SmartSwitchHaTrafficTest instance
        active_dut_index : Index of the DUT that is currently active (0 or 1)
        disruption_secs  : Allowed disruption window in seconds
    """
    logger.info("Starting traffic")
    ha_io.start_io_test()
    time.sleep(disruption_secs)

    logger.info("Stopping traffic and verifying")
    result = ha_io.stop_io_test()
    assert result, "Traffic verification failed: T2 did not receive expected packets"
    logger.info("Traffic verification passed with allowed disruption")


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


###############################################################################
# Test Class — syncd crash
###############################################################################


class TestSyncdCrash:
    """
    Verify HA behavior when syncd crashes on a DPU.

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
        ha_io,
    ):
        """
        Common test body for syncd crash scenarios.

        Steps:
            1. Start sending traffic
            2. Kill syncd on target DPU
            3. Verify HA state converges on crash DUT
            4. Verify HA state unchanged on peer DUT
            5. Verify traffic received by T2 with allowed disruption
            6. Wait for syncd to recover
        """
        logger.info(
            f"=== syncd crash on {crash_duthost.hostname} "
            f"DPU{crash_dpu_index} (scope: {crash_scope_key}) ==="
        )

        # Step 1: Start traffic
        logger.info("Step 1: Start sending traffic")
        ha_io.start_io_test()

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

        # Step 5: Stop traffic and verify T2 received packets
        logger.info("Step 5: Stop traffic and verify T2 received packets")
        time.sleep(TRAFFIC_DISRUPTION_SECS)
        result = ha_io.stop_io_test()
        assert result, (
            "Traffic verification failed: T2 did not receive expected packets "
            "within the allowed disruption window"
        )
        logger.info("Traffic verification passed with allowed disruption")

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
        duthosts,
        active_dut,
        standby_dut,
        setup_ha_config,
        setup_SmartSwitchHaTrafficTest,
        activate_dash_ha_from_json,
    ):
        """
        Variation 1: syncd crash on active DPU, traffic landing on active DPU.

        Expected:
            Control Plane : HA state converges eventually.
            Data Plane    : T2 receives packets with allowed disruption.
        """
        self._run_syncd_crash(
            crash_duthost=active_dut,
            crash_dpu_index=0,
            crash_scope_key=ACTIVE_SCOPE_KEY,
            expected_ha_state_after_crash="active",
            verify_duthost=standby_dut,
            verify_scope_key=STANDBY_SCOPE_KEY,
            expected_ha_state_verify="standby",
            ha_io=setup_SmartSwitchHaTrafficTest,
        )

    # ------------------------------------------------------------------
    # Variation 2: Crash on active DPU, traffic landing on standby DPU
    # ------------------------------------------------------------------
    def test_syncd_crash_active_dpu_traffic_on_standby(
        self,
        duthosts,
        active_dut,
        standby_dut,
        setup_ha_config,
        setup_SmartSwitchHaTrafficTest,
        activate_dash_ha_from_json,
    ):
        """
        Variation 2: syncd crash on active DPU, traffic landing on standby DPU.

        Expected:
            Control Plane : HA state converges eventually.
            Data Plane    : T2 receives packets with allowed disruption.
        """
        self._run_syncd_crash(
            crash_duthost=active_dut,
            crash_dpu_index=0,
            crash_scope_key=ACTIVE_SCOPE_KEY,
            expected_ha_state_after_crash="active",
            verify_duthost=standby_dut,
            verify_scope_key=STANDBY_SCOPE_KEY,
            expected_ha_state_verify="standby",
            ha_io=setup_SmartSwitchHaTrafficTest,
        )

    # ------------------------------------------------------------------
    # Variation 3: Crash on standby DPU, traffic landing on active DPU
    # ------------------------------------------------------------------
    def test_syncd_crash_standby_dpu_traffic_on_active(
        self,
        duthosts,
        active_dut,
        standby_dut,
        setup_ha_config,
        setup_SmartSwitchHaTrafficTest,
        activate_dash_ha_from_json,
    ):
        """
        Variation 3: syncd crash on standby DPU, traffic landing on active DPU.

        Expected:
            Control Plane : HA state remains unchanged.
            Data Plane    : T2 receives packets with allowed disruption.
        """
        self._run_syncd_crash(
            crash_duthost=standby_dut,
            crash_dpu_index=0,
            crash_scope_key=STANDBY_SCOPE_KEY,
            expected_ha_state_after_crash="standby",
            verify_duthost=active_dut,
            verify_scope_key=ACTIVE_SCOPE_KEY,
            expected_ha_state_verify="active",
            ha_io=setup_SmartSwitchHaTrafficTest,
        )

    # ------------------------------------------------------------------
    # Variation 4: Crash on standby DPU, traffic landing on standby DPU
    # ------------------------------------------------------------------
    def test_syncd_crash_standby_dpu_traffic_on_standby(
        self,
        duthosts,
        active_dut,
        standby_dut,
        setup_ha_config,
        setup_SmartSwitchHaTrafficTest,
        activate_dash_ha_from_json,
    ):
        """
        Variation 4: syncd crash on standby DPU, traffic landing on standby DPU.

        Expected:
            Control Plane : HA state remains unchanged.
            Data Plane    : T2 receives packets with allowed disruption.
        """
        self._run_syncd_crash(
            crash_duthost=standby_dut,
            crash_dpu_index=0,
            crash_scope_key=STANDBY_SCOPE_KEY,
            expected_ha_state_after_crash="standby",
            verify_duthost=active_dut,
            verify_scope_key=ACTIVE_SCOPE_KEY,
            expected_ha_state_verify="active",
            ha_io=setup_SmartSwitchHaTrafficTest,
        )
