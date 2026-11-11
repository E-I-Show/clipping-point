import unittest
def setUpModule(): raise RuntimeError("module setup boom")
class TestA(unittest.TestCase):
    def test_one(self): self.assertEqual(1, 1)
