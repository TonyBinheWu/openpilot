import unittest
from types import SimpleNamespace as NS

from openpilot.selfdrive.ui.sunnypilot.onroad.developer_diagnostics import DeveloperDiagnostics, WATCH_FIELDS, MAX_IDS, MAX_FRAMES


def car_state(**changes):
  values = dict.fromkeys(WATCH_FIELDS, False)
  values.update(gearShifter='park', buttonEvents=[])
  values.update(changes)
  return NS(**values)


class FakeSM(dict):
  def __init__(self):
    super().__init__(carState=car_state())
    self.valid = self.alive = {'carState': True}
    self.recv_frame = {'carState': 10}
    self.logMonoTime = {'carState': 100}


class FakeMessaging:
  def __init__(self):
    self.opened = []
    self.reads = []
    self.messages = {}

  def sub_sock(self, service, conflate):
    assert conflate
    self.opened.append(service)
    return service

  def recv_one_or_none(self, sock):
    self.reads.append(sock)
    return self.messages.pop(sock, None)


class TestDeveloperDiagnostics(unittest.TestCase):
  def test_peak_and_missing_temperatures(self):
    d = DeveloperDiagnostics()
    d.ingest_temperature(NS(tempC=65, memoryTempC=70), True, 1)
    d.ingest_temperature(NS(tempC=60, memoryTempC=75), True, 2)
    self.assertEqual((d.temperature, d.peak, d.memory_peak), (60, 65, 75))
    d.ingest_temperature(NS(tempC=0, memoryTempC=float('nan')), True, 3)
    self.assertIsNone(d.temperature)
    self.assertIsNone(d.memory_temperature)
    self.assertEqual(d.peak, 65)
    d.ingest_temperature(NS(tempC=100, memoryTempC=100), False, 4)
    self.assertEqual(d.peak, 65)

  def test_stale_live_reading_keeps_session_peak(self):
    d = DeveloperDiagnostics()
    d.ingest_temperature(NS(tempC=65, memoryTempC=70), True, 1)
    self.assertIn('HOTSPOT -- C | MAX 65.0 C', d.lines(4)[0])

  def test_signal_baseline_transitions_and_buttons(self):
    d = DeveloperDiagnostics()
    d.ingest_car_state(car_state(), 100, 1)
    self.assertEqual(len(d.events), 0)
    cs = car_state(leftBlinker=True, buttonEvents=[NS(type='cancel', pressed=True)])
    d.ingest_car_state(cs, 101, 2)
    self.assertEqual(len(d.events), 2)
    self.assertIn('leftBlinker: OFF -> ON', d.events[1][1])
    d.ingest_car_state(cs, 101, 3)
    self.assertEqual(len(d.events), 2)
    self.assertIn('BLINK L ON R OFF', d.lines(3)[2])
    self.assertIn('BLINK L -- R --', d.lines(6)[2])

  def test_history_is_bounded(self):
    d = DeveloperDiagnostics()
    for i in range(20):
      d.ingest_car_state(car_state(leftBlinker=bool(i % 2)), i, i)
    self.assertEqual(len(d.events), 6)
    for i in range(MAX_IDS + 10):
      d.ingest_can([NS(src=0, address=i, dat=b'1234')], i)
    self.assertEqual(len(d.frames), MAX_IDS)

  def test_raw_bus_identity_payload_changes_and_echoes(self):
    d = DeveloperDiagnostics()
    d.ingest_can([NS(src=0, address=123, dat=b'12'), NS(src=1, address=123, dat=b'34'),
                  NS(src=128, address=124, dat=b'56')], 1)
    d.ingest_can([NS(src=0, address=123, dat=b'13')], 2)
    self.assertEqual(set(d.frames), {(0, 123), (1, 123)})
    self.assertEqual(d.frames[(0, 123)][2], 2)
    self.assertTrue(any(line.startswith('*B0 0x7B') for line in d.lines(2)))

  def test_work_per_batch_capped(self):
    d = DeveloperDiagnostics()
    d.ingest_can([NS(src=0, address=i, dat=b'1') for i in range(MAX_FRAMES + 10)], 1)
    self.assertEqual(d.sample_count, MAX_FRAMES)
    self.assertEqual(d.capped_batches, 1)

  def test_toggle_off_releases_sockets_and_clears_everything(self):
    d, sm, messaging = DeveloperDiagnostics(), FakeSM(), FakeMessaging()
    d.update(sm, False, 1, 1, messaging)
    self.assertEqual(messaging.opened, [])
    d.update(sm, True, 1, 2, messaging)
    self.assertEqual(messaging.opened, ['can', 'chestnutState'])
    d.ingest_temperature(NS(tempC=60, memoryTempC=65), True, 2)
    d.ingest_can([NS(src=0, address=1, dat=b'1')], 2)
    d.update(sm, False, 1, 3, messaging)
    self.assertIsNone(d._can_sock)
    self.assertIsNone(d._gpu_sock)
    self.assertIsNone(d.peak)
    self.assertFalse(d.frames)
    self.assertFalse(d.values)
    self.assertFalse(d.events)
    d.update(sm, True, 1, 4, messaging)
    self.assertIsNone(d.peak)
    self.assertEqual(len(messaging.opened), 4)

  def test_new_drive_resets_and_reads_only_one_batch(self):
    d, sm, messaging = DeveloperDiagnostics(), FakeSM(), FakeMessaging()
    messaging.messages['chestnutState'] = NS(valid=True, chestnutState=NS(tempC=50, memoryTempC=55))
    d.update(sm, True, 1, 1, messaging)
    self.assertEqual(messaging.reads, ['can', 'chestnutState'])
    self.assertEqual(d.peak, 50)
    d.update(sm, True, 2, 2, messaging)
    self.assertIsNone(d.peak)

  def test_socket_failure_is_visible_and_retries_are_bounded(self):
    d, sm, messaging = DeveloperDiagnostics(), FakeSM(), FakeMessaging()
    def fail(*args, **kwargs):
      raise RuntimeError('unavailable')
    messaging.sub_sock = fail
    d.update(sm, True, 1, 1, messaging)
    self.assertTrue(d.error)
    self.assertTrue(any('ERROR' in line for line in d.lines(1)))
    d.update(sm, True, 1, 2, messaging)
    self.assertEqual(d._retry_at, 3)

  def test_can_fd_preview_is_explicitly_truncated(self):
    d = DeveloperDiagnostics()
    d.ingest_can([NS(src=0, address=1, dat=bytes(range(64)))], 1)
    self.assertIn('[64] 0001020304050607..', d.lines(1)[-1])


if __name__ == '__main__':
  unittest.main()
