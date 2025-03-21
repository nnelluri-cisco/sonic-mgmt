import pytest

from tests.common.helpers.tacacs.tacacs_helper import ssh_remote_run, ssh_remote_run_retry, check_tacacs  # noqa: F401
from tests.common.utilities import check_output

pytestmark = [
    pytest.mark.disable_loganalyzer,
    pytest.mark.topology('any', 't1-multi-asic'),
    pytest.mark.device_type('vs')
]


def test_rw_user(localhost, duthosts, enum_rand_one_per_hwsku_hostname, tacacs_creds, check_tacacs):  # noqa: F811
    """test tacacs rw user
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    dutip = duthost.mgmt_ip
    res = ssh_remote_run(localhost, dutip, tacacs_creds['tacacs_rw_user'],
                         tacacs_creds['tacacs_rw_user_passwd'], "cat /etc/passwd")

    check_output(res, 'testadmin', 'remote_user_su')


def test_rw_user_ipv6(localhost, duthosts, ptfhost, enum_rand_one_per_hwsku_hostname,
                      tacacs_creds, check_tacacs_v6):
    """test tacacs rw user
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    dutip = duthost.mgmt_ip
    res = ssh_remote_run_retry(localhost, dutip, ptfhost,
                               tacacs_creds['tacacs_rw_user'],
                               tacacs_creds['tacacs_rw_user_passwd'],
                               "cat /etc/passwd")

    check_output(res, 'testadmin', 'remote_user_su')
