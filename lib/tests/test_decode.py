import pathlib
import unittest

from eitai_elebox import BatteryState, Frame, parse_candump_line

DATA = pathlib.Path(__file__).parent / "data"


def load(name: str) -> BatteryState:
    state = BatteryState()
    for line in (DATA / name).read_text().splitlines():
        f = parse_candump_line(line)
        if f:
            state.update(f)
    return state


class TestFrames(unittest.TestCase):
    def test_cell_voltage_frame(self):
        s = BatteryState()
        s.update(Frame(0x1811F589, bytes.fromhex("01000CF30CF00CF2")))
        self.assertEqual(s.modules[9].cells_mv[:3], [3315, 3312, 3314])

    def test_last_cell_frame_has_one_cell(self):
        s = BatteryState()
        s.update(Frame(0x1811F580, bytes.fromhex("10000CEF")))
        self.assertEqual(s.modules[0].cells_mv[15], 3311)
        self.assertEqual(s.modules[0].cells_mv[:15], [None] * 15)

    def test_temperatures(self):
        s = BatteryState()
        s.update(Frame(0x1812F580, bytes.fromhex("010048494849")))
        self.assertEqual(s.modules[0].temps_c, [32, 33, 32, 33])

    def test_module_voltage(self):
        s = BatteryState()
        s.update(Frame(0x1819F585, bytes.fromhex("0100EE000210")))
        self.assertEqual(s.modules[5].voltage_v, 52.8)

    def test_master_reference(self):
        s = BatteryState()
        s.update(Frame(0x181080F5, bytes.fromhex("FFFF0CED3E80FFFF")))
        self.assertEqual(s.reference_cell_mv, 3309)
        self.assertEqual(s.modules, {})

    def test_standard_frames_ignored(self):
        s = BatteryState()
        s.update(Frame(0x305, b"\x00" * 8, extended=False))
        self.assertEqual(s.frames_total, 0)


class TestCapture(unittest.TestCase):
    def setUp(self):
        self.d = load("capture_idle.log").as_dict()

    def test_topology(self):
        self.assertEqual(self.d["system"]["module_count"], 10)
        self.assertEqual(self.d["system"]["cell_count"], 160)

    def test_pack_voltage_plausible(self):
        self.assertAlmostEqual(self.d["system"]["pack_voltage_v"], 529.4, delta=1.0)

    def test_weak_cell_found(self):
        sysd = self.d["system"]
        self.assertEqual((sysd["cell_min_module"], sysd["cell_min_cell"]), (6, 7))
        self.assertLess(sysd["cell_min_mv"], 3280)

    def test_module_voltage_matches_cell_sum(self):
        for m in self.d["modules"]:
            self.assertAlmostEqual(m["voltage_v"], sum(m["cells_mv"]) / 1000, delta=0.15)

    def test_system_records_present(self):
        self.assertEqual(sorted(self.d["system"]["system_records_raw"]), ["07", "08", "09", "0a", "0b", "0c"])


if __name__ == "__main__":
    unittest.main()
