import unittest
class TestA(unittest.TestCase):
    @unittest.skip("later")
    def test_one(self): self.assertEqual(1, 2)
