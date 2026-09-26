import pytest
from unittest.mock import patch, MagicMock

def test_check_namespace_exists():
    from controller.main import check_namespace_exists
    
    with patch("controller.main.core_v1.read_namespace") as mock_read:
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
    
    with patch("controller.main.core_v1.delete_namespace") as mock_delete:
        delete_namespace("test-ns")
        mock_delete.assert_called_once_with(name="test-ns", propagation_policy="Background")
        
        # Should gracefully handle 404 (already deleted)
        from kubernetes.client.exceptions import ApiException
        mock_delete.reset_mock()
        mock_delete.side_effect = ApiException(status=404)
        delete_namespace("already-deleted-ns")  # Should not raise exception

def test_get_github_app_token_not_github():
    from controller.main import get_github_app_token
    # If not a github.com repo, should return empty string
    assert get_github_app_token("https://gitlab.com/repo.git") == ""
    assert get_github_app_token("http://bitbucket.org/repo") == ""

