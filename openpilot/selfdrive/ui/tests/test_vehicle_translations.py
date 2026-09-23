from pathlib import Path
import unittest

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.translations.potools import extract_strings, parse_po


VEHICLE_UI = Path(BASEDIR) / "openpilot/selfdrive/ui/sunnypilot/layouts/settings/vehicle"
TRANSLATIONS = Path(BASEDIR) / "openpilot/selfdrive/ui/translations"


class TestVehicleTranslations(unittest.TestCase):
  def test_all_vehicle_messages_have_traditional_chinese(self):
    sources = [str(path.relative_to(BASEDIR)) for path in VEHICLE_UI.rglob("*.py")]
    extracted = extract_strings(sources, BASEDIR)
    _, entries = parse_po(TRANSLATIONS / "app_zh-CHT.po")
    catalog = {entry.msgid: entry.msgstr for entry in entries}

    self.assertGreater(len(extracted), 40)
    for entry in extracted:
      with self.subTest(source=entry.msgid):
        self.assertTrue(catalog.get(entry.msgid), "missing or empty Traditional Chinese translation")


if __name__ == "__main__":
  unittest.main()
