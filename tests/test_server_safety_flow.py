import unittest

from fastapi_route_inventory import registered_route_paths

import server


class ServerSafetyFlowTests(unittest.TestCase):
    def test_existing_app_registers_live_safety_observation_endpoint(self):
        routes = registered_route_paths(server.app)

        self.assertIn("/pdr/update", routes)
        self.assertIn("/safety/observations", routes)


if __name__ == "__main__":
    unittest.main()
