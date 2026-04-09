import unittest

from server.npu.device_selection import parse_visible_device_ids, select_default_npu_ids


class DeviceSelectionTests(unittest.TestCase):
    def test_parse_visible_device_ids(self):
        self.assertEqual(parse_visible_device_ids("4,5,6,7"), [4, 5, 6, 7])
        self.assertEqual(parse_visible_device_ids(" 4, x, 6 "), [4, 6])
        self.assertIsNone(parse_visible_device_ids(""))
        self.assertIsNone(parse_visible_device_ids(None))

    def test_select_default_npu_ids(self):
        self.assertEqual(select_default_npu_ids([0, 1, 2]), [0, 1, 2])
        self.assertEqual(select_default_npu_ids([0, 1, 2, 3, 4, 5, 6, 7]), [4, 5, 6, 7])
        self.assertEqual(select_default_npu_ids([7, 5, 6, 4, 3]), [4, 5, 6, 7])


if __name__ == "__main__":
    unittest.main()
