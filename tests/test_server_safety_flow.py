import unittest

import server


class ServerSafetyFlowTests(unittest.TestCase):
    def test_existing_app_registers_live_safety_observation_endpoint(self):
        routes = {route.path for route in server.app.routes}

        self.assertIn("/pdr/update", routes)
        self.assertIn("/safety/observations", routes)


if __name__ == "__main__":
    unittest.main()
