"""
This file contains test functions for MEI export
"""

import unittest

from tests import MEI_TESTFILES
from partitura import load_musicxml, load_mei
import partitura.score as score
from partitura.io.importmei import _parse_mei, _ns_name, _handle_main_staff_group
from lxml import etree


# class TestSaveMEI(unittest.TestCase):

#     def test_save_mei(self):

#         with open(EXAMPLE_MEI, 'r') as f:
#             target_mei = f.read()

#         mei = save_mei(load_musicxml(EXAMPLE_MUSICXML), title_text='score_example')
#         msg = "Export of MEI of file {} does not yield identical result".format(EXAMPLE_MEI)

#         self.assertTrue(mei.decode('utf-8') == target_mei, msg)


class TestImportMEI(unittest.TestCase):
    def test_main_part_group1(self):
        document, ns = _parse_mei(MEI_TESTFILES[5])
        main_partgroup_el = document.find(_ns_name("staffGrp", ns, True))
        part_list = _handle_main_staff_group(main_partgroup_el, ns)
        self.assertTrue(len(part_list) == 2)
        # first partgroup
        self.assertTrue(isinstance(part_list[0], score.PartGroup))
        self.assertTrue(part_list[0].group_symbol == "bracket")
        self.assertTrue(part_list[0].group_name is None)
        self.assertTrue(part_list[0].id == "sl1ipm2")
        # first partgroup first part
        self.assertTrue(part_list[0].children[0].id == "P1")
        self.assertTrue(part_list[0].children[0].part_name == "S")
        self.assertTrue(part_list[0].children[0]._quarter_durations[0] == 12)
        # first partgroup second part
        self.assertTrue(part_list[0].children[1].id == "P2")
        self.assertTrue(part_list[0].children[1].part_name == "A")
        self.assertTrue(part_list[0].children[1]._quarter_durations[0] == 12)
        # first partgroup third part
        self.assertTrue(part_list[0].children[2].id == "P3")
        self.assertTrue(part_list[0].children[2].part_name == "T")
        self.assertTrue(part_list[0].children[2]._quarter_durations[0] == 12)
        # first partgroup fourth part
        self.assertTrue(part_list[0].children[3].id == "P4")
        self.assertTrue(part_list[0].children[3].part_name == "B")
        self.assertTrue(part_list[0].children[3]._quarter_durations[0] == 12)
        # second partgroup
        self.assertTrue(isinstance(part_list[1], score.PartGroup))
        self.assertTrue(part_list[1].group_symbol == "brace")
        self.assertTrue(part_list[1].group_name == "Piano")
        self.assertTrue(part_list[1].id == "P5")

    def test_main_part_group2(self):
        document, ns = _parse_mei(MEI_TESTFILES[4])
        main_partgroup_el = document.find(_ns_name("staffGrp", ns, True))
        part_list = _handle_main_staff_group(main_partgroup_el, ns)
        self.assertTrue(len(part_list) == 1)
        self.assertTrue(isinstance(part_list[0], score.PartGroup))


if __name__ == "__main__":
    unittest.main()

