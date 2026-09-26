import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# Add controller dir to sys.path so its internal absolute imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "controller")))

def test_check_namespace_exists():
    from controller.main import check_namespace_exists
    
    with patch("controller.main.k8s_core_api.read_namespace") as mock_read:
        # Mock success
        mock_read.return_value = MagicMock()
        assert check_namespace_exists("test-ns") == True
        mock_read.assert_called_once_with(name="test-ns")
        
        # Mock failure (NotFound)
        from kubernetes.client.exceptions import ApiException
        mock_read.reset_mock()
        mock_read.side_effect = ApiException(status=404)
        assert check_namespace_exists("nonexistent-ns") == False

def test_delete_namespace():
    from controller.main import delete_namespace
    
    with patch("controller.main.k8s_core_api.delete_namespace") as mock_delete:
        delete_namespace("test-ns")
        mock_delete.assert_called_once_with(name="test-ns")
        
        # Should gracefully handle 404 (already deleted)
        from kubernetes.client.exceptions import ApiException
        mock_delete.reset_mock()
        mock_delete.side_effect = ApiException(status=404)
        delete_namespace("already-deleted-ns")  # Should not raise exception

def test_get_github_app_token_not_github():
    from controller.main import get_github_app_token
    # If not a github.com repo, should return None
    assert get_github_app_token("https://gitlab.com/repo.git") is None
    assert get_github_app_token("http://bitbucket.org/repo") is None


