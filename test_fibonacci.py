import unittest
from fibonacci import fibonacci

class TestFib(unittest.TestCase):
    def test_fib(self):
        self.assertEqual(fibonacci(7), 13)

if __name__ == "__main__":
    unittest.main()
