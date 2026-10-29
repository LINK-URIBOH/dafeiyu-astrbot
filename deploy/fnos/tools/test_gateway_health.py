import unittest
from unittest.mock import patch
import gateway_health
import heal_ws


class HealthTests(unittest.TestCase):
    def test_restart_grace_waits_for_builtin_reconnect_without_legacy_calls(self):
        with patch.object(gateway_health,'backend',return_value='snowluma'), \
             patch.object(gateway_health,'snowluma_health',return_value=True), \
             patch.object(heal_ws,'adapter_connected',side_effect=[False,False,True]), \
             patch.object(heal_ws.time,'sleep'), \
             patch.object(heal_ws,'_login') as legacy_login:
            self.assertEqual(heal_ws.main(),0)
            legacy_login.assert_not_called()

    def test_offline_deadline_does_not_restart_or_enable_old_gateway(self):
        with patch.object(gateway_health,'backend',return_value='snowluma'), \
             patch.object(gateway_health,'snowluma_health',return_value=False), \
             patch.object(heal_ws,'adapter_connected',return_value=False), \
             patch.object(heal_ws.time,'monotonic',side_effect=[0,31]), \
             patch.object(heal_ws,'_login') as legacy_login:
            self.assertEqual(heal_ws.main(),1)
            legacy_login.assert_not_called()


if __name__=='__main__':unittest.main()
