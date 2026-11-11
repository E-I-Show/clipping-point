import threading, unittest
class TestA(unittest.TestCase):
    def test_one(self):
        t = threading.Thread(target=lambda: 1/0); t.start(); t.join()
