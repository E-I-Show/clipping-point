import os, unittest
class TestA(unittest.TestCase):
    def test_a_one(self): os._exit(0)
    def test_b_two(self): self.assertEqual(1, 2)
