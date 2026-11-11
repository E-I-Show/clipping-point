import unittest
class TestA(unittest.TestCase):
    def test_one(self): raise RuntimeError("boom")
    def test_two(self): self.assertEqual(2, 2)
