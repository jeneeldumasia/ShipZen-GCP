import os
import sys
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/shipzen_test")
WORKER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "worker"))
if WORKER_DIR not in sys.path:
    sys.path.insert(0, WORKER_DIR)

import pytest
from unittest.mock import patch, MagicMock

# --- Worker State Machine Tests ---

def test_update_state_uses_update():
    """
    Test that update_state executes an UPDATE statement and not an INSERT
    to avoid violating the NOT NULL constraints.
    """
    with patch('worker.state_machine.get_db_connection') as mock_get_conn:
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.rowcount = 1
        
        from worker.state_machine import StateMachine, DeploymentState
        sm = StateMachine()
        sm._redis = MagicMock()  # Mock Redis to avoid network connection in unit test
        
        sm.update_state("deploy_123", DeploymentState.BUILDING)
        
        # Verify the query executed was an UPDATE
        call_args = mock_cur.execute.call_args[0][0]
        assert "UPDATE deployments" in call_args
        assert "INSERT" not in call_args
