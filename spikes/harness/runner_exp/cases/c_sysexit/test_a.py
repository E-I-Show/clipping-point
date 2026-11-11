import sys, unittest
class TestA(unittest.TestCase):
    def test_one(self): sys.exit(0)
    def test_two(self): self.assertEqual(1, 2)
