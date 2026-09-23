import subprocess

from openpilot.common.hardware.comma.modem import Modem, PPPSession, State


def test_missing_gsm_enabled_param_defaults_to_enabled(mocker):
  modem = Modem.__new__(Modem)
  mocker.patch.object(modem, "_read_param", return_value="")

  assert modem._is_enabled()


def test_disabled_modem_waits_for_port_before_reset(mocker):
  modem = Modem.__new__(Modem)
  mocker.patch.object(modem, "_is_enabled", return_value=True)
  mocker.patch("openpilot.common.hardware.comma.modem.os.path.exists", return_value=False)
  at = mocker.patch.object(modem, "_at")

  assert modem._do_disabled() == State.DISABLED
  at.assert_not_called()


def test_enabling_modem_performs_full_reset(mocker):
  modem = Modem.__new__(Modem)
  modem.S = {}
  mocker.patch.object(modem, "_is_enabled", return_value=True)
  mocker.patch("openpilot.common.hardware.comma.modem.os.path.exists", return_value=True)
  at = mocker.patch.object(modem, "_at")
  mocker.patch.object(modem, "_publish_state")

  assert modem._do_disabled() == State.INITIALIZING
  at.assert_called_once_with("AT+CFUN=1,1")


def test_ppp_installs_interface_specific_nat(mocker):
  success = subprocess.CompletedProcess([], 0, "", "")
  missing = subprocess.CompletedProcess([], 1, "", "")

  def run(command, **kwargs):
    return missing if "-C" in command else success

  runner = mocker.patch("openpilot.common.hardware.comma.modem.subprocess.run", side_effect=run)

  PPPSession.install_tethering_forwarding()

  commands = [call.args[0] for call in runner.call_args_list]
  assert any("-A" in command and "POSTROUTING" in command and "ppp0" in command and "MASQUERADE" in command for command in commands)
  assert any("-I" in command and "FORWARD" in command and "wlan0" in command and "ppp0" in command for command in commands)


def test_ppp_routes_tethering_subnet_through_cellular_table(mocker):
  success = subprocess.CompletedProcess([], 0, "", "")
  ppp = PPPSession()
  mocker.patch("openpilot.common.hardware.comma.modem.subprocess.run", return_value=success)
  mocker.patch.object(ppp, "cleanup_routes")
  mocker.patch.object(ppp, "install_tethering_forwarding")
  verify = mocker.patch.object(ppp, "verify_tethering_route", return_value=True)

  assert ppp.maybe_install_routes("10.0.0.2", "10.64.64.64")

  commands = [call.args[0] for call in subprocess.run.call_args_list]
  assert ["sudo", "ip", "rule", "add", "priority", "11010", "from", "192.168.43.0/24", "table", "1000"] in commands
  verify.assert_called_once_with()


def test_verify_tethering_route_requires_ppp0(mocker):
  success = subprocess.CompletedProcess([], 0, "1.1.1.1 via 10.64.64.64 dev ppp0 table 1000", "")
  runner = mocker.patch("openpilot.common.hardware.comma.modem.subprocess.run", return_value=success)

  assert PPPSession.verify_tethering_route()
  assert runner.call_args.args[0][-2:] == ["iif", "wlan0"]
