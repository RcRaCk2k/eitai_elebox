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

    def test_soc_and_counters(self):
        s = BatteryState()
        # live values of 23 Oct 2026
        for rec in ("0705000400E651", "080500012B68", "09050014 12FC", "0A050005A53C", "0B0500000000", "0C05001B0082"):
            s.update(Frame(0x1833F4E8, bytes.fromhex(rec.replace(" ", ""))))
        sysd = s.as_dict()["system"]
        self.assertEqual(sysd["soc_pct"], 81)
        self.assertEqual(sysd["charge_ah_total"], 26237.4)
        self.assertEqual(sysd["discharge_ah_total"], 7664.8)
        self.assertEqual(sysd["charge_kwh_total"], 13155.8)
        self.assertEqual(sysd["discharge_kwh_total"], 3699.8)
        self.assertEqual((sysd["charge_ah_current"], sysd["charge_kwh_current"]), (0, 0))
        self.assertEqual((sysd["discharge_ah_current"], sysd["discharge_kwh_current"]), (2.7, 1.3))

    def test_current_charge_record(self):
        s = BatteryState()
        s.update(Frame(0x1833F4E8, bytes.fromhex("0B0500140064")))  # seen once in a capture
        sysd = s.as_dict()["system"]
        self.assertEqual((sysd["charge_ah_current"], sysd["charge_kwh_current"]), (2.0, 1.0))

    def test_balancing(self):
        s = BatteryState()
        s.update(Frame(0x1815F585, bytes.fromhex("0001000000000000")))
        s.update(Frame(0x184085F5, bytes.fromhex("0100000000000000")))
        m = s.modules[5].as_dict()
        self.assertIs(m["balancing"], False)
        self.assertEqual(m["balancing_cells"], [])
        self.assertEqual(m["balance_cmd_raw"], "0100000000000000")
        s.update(Frame(0x1815F585, bytes.fromhex("0001804100000000")))
        self.assertEqual(s.modules[5].as_dict()["balancing_cells"], [1, 7, 16])
        self.assertIs(s.modules[5].as_dict()["balancing"], True)
        s.update(Frame(0x1815F585, bytes.fromhex("01FFFFFF00000000")))  # other record: ignored
        self.assertEqual(s.modules[5].as_dict()["balancing_cells"], [1, 7, 16])
        self.assertIsNone(s.modules.get(0))

    def test_faults(self):
        s = BatteryState()
        s.update(Frame(0x1841F585, bytes.fromhex("0000000000000000")))
        m = s.modules[5].as_dict()
        self.assertIs(m["fault"], False)
        self.assertEqual(m["faults"], [])
        s.update(Frame(0x1841F585, bytes.fromhex("0110101002000000")))
        self.assertEqual(s.modules[5].as_dict()["faults"],
                         ["supply_undervoltage", "balancer_detection_1", "measurement_chip_1", "passive_balancing",
                          "temp_wire"])

    def test_supply_voltage(self):
        s = BatteryState()
        s.update(Frame(0x1819F585, bytes.fromhex("0100EE000210")))
        self.assertEqual(s.modules[5].supply_voltage_v, 23.8)

    def test_inventory_flags_unknown_ids(self):
        s = BatteryState()
        s.update(Frame(0x1899F585, bytes.fromhex("01")))
        s.update(Frame(0x1811F580, bytes.fromhex("01000cee0ceb0cee")))
        inv = {i["id"]: i for i in s.inventory()}
        self.assertFalse(inv["1899F585"]["known"])
        self.assertTrue(inv["1811F580"]["known"])
        self.assertEqual(inv["1899F585"]["last_data"], "01")

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
        self.assertGreater(sysd["cell_min_below_avg_mv"], 30)

    def test_soc_from_capture(self):
        self.assertEqual(self.d["system"]["soc_pct"], 28)

    def test_no_module_balancing_or_fault_in_capture(self):
        self.assertEqual([m["balancing"] for m in self.d["modules"]], [False] * 10)
        self.assertEqual([m["fault"] for m in self.d["modules"]], [False] * 10)

    def test_module_voltage_matches_cell_sum(self):
        for m in self.d["modules"]:
            self.assertAlmostEqual(m["voltage_v"], sum(m["cells_mv"]) / 1000, delta=0.15)

    def test_inventory_all_ids_known(self):
        inv = load("capture_idle.log").inventory()
        self.assertEqual(len(inv), 112)  # 11 message types x 10 modules + 2 system IDs
        self.assertEqual([i["id"] for i in inv if not i["known"]], [])
        faults = next(i for i in inv if i["id"] == "1841F585")
        self.assertEqual(faults["payloads"], {"0000000000000000": faults["count"]})
        self.assertAlmostEqual(faults["period_ms"], 790, delta=40)

    def test_system_records_present(self):
        self.assertEqual(sorted(self.d["system"]["system_records_raw"]), ["07", "08", "09", "0a", "0b", "0c"])


if __name__ == "__main__":
    unittest.main()
