import unittest
class TestA(unittest.TestCase):
    def test_one(self):
        for i in range(3):
            with self.subTest(i=i): self.assertNotEqual(i, 1)
