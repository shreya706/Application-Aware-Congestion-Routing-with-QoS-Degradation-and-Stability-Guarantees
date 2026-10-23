"""Regression checks for controller state that previously broke OS-Ken startup."""
import tempfile
import unittest
from unittest.mock import patch

import controller


class ControllerInitializationTests(unittest.TestCase):
    def test_controller_preserves_osken_event_queue(self):
        with tempfile.TemporaryFile(mode="w+") as events_file:
            with tempfile.TemporaryFile(mode="w+") as monitor_file:
                def open_test_logs(app):
                    app.events_file = events_file
                    app.monitor = monitor_file

                with patch.object(controller.ApplicationAwareController,
                                  "_open_logs", open_test_logs):
                    app = controller.ApplicationAwareController()
                    self.assertTrue(hasattr(app.events, "get"))
                    self.assertIsNot(app.events, app.events_file)


if __name__ == "__main__":
    unittest.main()
