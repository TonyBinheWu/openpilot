import subprocess

from openpilot.system.ui.lib.wifi_manager import TETHERING_DNS_SERVERS, WifiManager


class InlineThread:
  def __init__(self, target, daemon=False):
    self.target = target

  def start(self):
    self.target()


def test_tethering_ipv4_settings_enable_sharing_and_dns():
  settings = WifiManager._tethering_ipv4_settings()

  assert settings['method'] == ('s', 'shared')
  assert settings['dns-data'] == ('as', list(TETHERING_DNS_SERVERS))


def test_enable_tethering_configures_forwarding(mocker):
  wm = WifiManager.__new__(WifiManager)
  wm._exit = True
  wm._tethering_ssid = "weedle-test"
  wm._tethering_clients = []
  update_connection = mocker.patch.object(wm, "_update_tethering_connection")
  activate_connection = mocker.patch.object(wm, "activate_connection")
  configure_forwarding = mocker.patch.object(wm, "_configure_tethering_forwarding")
  mocker.patch.object(wm, "_update_tethering_clients")
  mocker.patch("openpilot.system.ui.lib.wifi_manager.threading.Thread", InlineThread)

  wm.set_tethering_active(True)

  update_connection.assert_called_once_with()
  activate_connection.assert_called_once_with("weedle-test", block=True)
  configure_forwarding.assert_called_once_with(True)


def test_disable_tethering_deactivates_hotspot(mocker):
  wm = WifiManager.__new__(WifiManager)
  wm._exit = True
  wm._tethering_ssid = "weedle-test"
  wm._tethering_clients = []
  deactivate_connection = mocker.patch.object(wm, "_deactivate_connection")
  configure_forwarding = mocker.patch.object(wm, "_configure_tethering_forwarding")
  mocker.patch("openpilot.system.ui.lib.wifi_manager.threading.Thread", InlineThread)

  wm.set_tethering_active(False)

  deactivate_connection.assert_called_once_with("weedle-test")
  configure_forwarding.assert_called_once_with(False)


def test_forwarding_rules_include_nat_dns_and_mss_clamping(mocker):
  success = subprocess.CompletedProcess([], 0, "", "")
  mocker.patch.object(WifiManager, "_find_executable", return_value="/usr/sbin/sysctl")
  run_privileged = mocker.patch.object(WifiManager, "_run_privileged", return_value=success)
  run_iptables = mocker.patch.object(WifiManager, "_run_iptables", return_value=success)

  WifiManager._configure_tethering_forwarding(True)

  run_privileged.assert_called_once()
  rules = [call.args[1] for call in run_iptables.call_args_list]
  assert any("MASQUERADE" in rule for rule in rules)
  assert any("--dport" in rule and "53" in rule for rule in rules)
  assert any("--clamp-mss-to-pmtu" in rule for rule in rules)


def test_find_executable_checks_sbin_when_path_is_restricted(mocker):
  mocker.patch("openpilot.system.ui.lib.wifi_manager.shutil.which", return_value=None)
  mocker.patch("openpilot.system.ui.lib.wifi_manager.os.path.isfile", side_effect=lambda path: path == "/usr/sbin/iptables")
  mocker.patch("openpilot.system.ui.lib.wifi_manager.os.access", return_value=True)

  assert WifiManager._find_executable(("iptables",)) == "/usr/sbin/iptables"


def test_connected_clients_include_associated_stations(mocker):
  wm = WifiManager.__new__(WifiManager)
  wm._exit = True
  wm._tethering_clients = []
  mocker.patch.object(wm, "is_tethering_active", return_value=True)
  mocker.patch.object(wm, "_find_executable", side_effect=lambda names: f"/usr/sbin/{names[0]}")
  mocker.patch("openpilot.system.ui.lib.wifi_manager.subprocess.run",
               return_value=subprocess.CompletedProcess([], 0, "192.168.43.23 dev wlan0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n", ""))
  mocker.patch.object(wm, "_run_privileged",
                      return_value=subprocess.CompletedProcess([], 0, "Station aa:bb:cc:dd:ee:ff (on wlan0)\n", ""))

  wm._update_tethering_clients()

  assert [(client.ip_address, client.mac_address) for client in wm.tethering_clients] == [
    ("192.168.43.23", "aa:bb:cc:dd:ee:ff"),
  ]
