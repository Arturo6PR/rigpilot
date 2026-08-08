import unittest

import rigpilot


class ProjectSmokeTests(unittest.TestCase):
    def test_package_has_version(self) -> None:
        self.assertRegex(rigpilot.__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
