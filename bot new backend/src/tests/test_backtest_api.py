"""
Comprehensive test suite for Backtest API

Run with: pytest tests/test_backtest_api.py -v
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import tempfile
from pathlib import Path

# Adjust imports based on your project structure
from src.main import app  # Your FastAPI app
from src.db.models import BacktestRun
from src.db.session import SessionLocal


@pytest.fixture
def client():
    """Test client fixture"""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Mock database session"""
    with patch("src.api.routes_backtest.SessionLocal") as mock:
        db = MagicMock()
        mock.return_value = db
        yield db


@pytest.fixture
def temp_features_file():
    """Create a temporary features file for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        features_dir = Path(tmpdir) / "features"
        features_dir.mkdir(parents=True)

        # Create a dummy parquet file
        features_file = features_dir / "BTCUSDT_1h_features.parquet"
        features_file.write_bytes(b"dummy parquet data")

        with patch("src.api.routes_backtest.settings") as mock_settings:
            mock_settings.data_dir = tmpdir
            yield features_file


class TestHealthCheck:
    """Test health check endpoint"""

    def test_health_check(self, client):
        response = client.get("/backtest/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestStrategyInfo:
    """Test strategy info endpoint"""

    def test_strategy_info(self, client):
        response = client.get("/backtest/strategy/info")
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "EMA Crossover + RSI Thresholds"
        assert data["ai_driven"] is False
        assert data["signal_generation"] == "deterministic"
        assert "parameters" in data
        assert "ema_fast" in data["parameters"]
        assert "ema_slow" in data["parameters"]
        assert "rsi_period" in data["parameters"]


class TestDatasetFingerprint:
    """Test dataset fingerprint endpoint"""

    def test_dataset_fingerprint_success(self, client, temp_features_file):
        response = client.get(
            "/backtest/dataset/fingerprint",
            params={"symbol": "BTCUSDT", "timeframe": "1h"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["ok"] is True
        assert data["symbol"] == "BTCUSDT"
        assert data["timeframe"] == "1h"
        assert "sha256" in data
        assert "bytes" in data
        assert "mtime_utc" in data

    def test_dataset_fingerprint_not_found(self, client):
        # Path(...) / a / b must chain to one object with exists() == False (MagicMock / is truthy otherwise).
        chain = MagicMock()
        chain.__truediv__.return_value = chain
        chain.exists.return_value = False
        with patch("src.api.routes_backtest.Path", return_value=chain):
            response = client.get(
                "/backtest/dataset/fingerprint",
                params={"symbol": "NONEXISTENT", "timeframe": "1h"},
            )
            assert response.status_code == 404


class TestRunBacktest:
    """Test backtest run endpoint"""

    @patch("src.api.routes_backtest.create_backtest_run")
    @patch("src.api.routes_backtest.run_backtest_for_run_id")
    def test_run_backtest_success(
        self, mock_run_backtest, mock_create_run, client, temp_features_file
    ):
        # Mock the create_backtest_run to return a run_id
        mock_create_run.return_value = 123

        payload = {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "initial_balance": 10000.0,
            "risk": {
                "max_position_pct": 0.1,
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.04,
                "fee_pct": 0.001,
                "cooldown_minutes_after_loss": 60,
            },
            "seed": 42,
        }

        response = client.post("/backtest/run", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["ok"] is True
        assert data["run_id"] == 123
        assert data["status"] == "running"
        assert data["seed"] == 42
        assert "dataset_sha256" in data

        # Verify create_backtest_run was called
        mock_create_run.assert_called_once()

    def test_run_backtest_invalid_params(self, client):
        payload = {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "initial_balance": -1000.0,  # Invalid: negative balance
        }

        response = client.post("/backtest/run", json=payload)
        assert response.status_code == 422  # Validation error

    @patch("src.api.routes_backtest._ensure_features_file")
    @patch("src.api.routes_backtest._dataset_sha256_for")
    def test_run_backtest_missing_dataset(self, mock_sha, mock_ensure, client):
        mock_sha.side_effect = HTTPException(
            status_code=404,
            detail="Features file not found",
        )
        payload = {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "initial_balance": 10000.0,
        }

        response = client.post("/backtest/run", json=payload)
        assert response.status_code == 404


class TestGetBacktestRun:
    """Test get backtest run endpoint"""

    def test_get_backtest_run_success(self, client, mock_db):
        # Create a mock run object
        mock_run = Mock(spec=BacktestRun)
        mock_run.id = 1
        mock_run.symbol = "BTCUSDT"
        mock_run.timeframe = "1h"
        mock_run.status = "success"
        mock_run.started_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_run.finished_at = datetime(2024, 1, 1, 13, 0, 0)
        mock_run.initial_balance = 10000.0
        mock_run.final_balance = 11500.0
        mock_run.total_return_pct = 15.0
        mock_run.max_drawdown_pct = -5.0
        mock_run.trades_count = 50
        mock_run.notes = "Test run"

        mock_db.query.return_value.filter.return_value.first.return_value = mock_run

        response = client.get("/backtest/1")
        assert response.status_code == 200
        data = response.json()

        assert data["ok"] is True
        assert data["run"]["id"] == 1
        assert data["run"]["symbol"] == "BTCUSDT"
        assert data["run"]["status"] == "success"
        assert data["run"]["final_balance"] == 11500.0
        assert data["run"]["total_return_pct"] == 15.0

    def test_get_backtest_run_not_found(self, client, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None

        response = client.get("/backtest/999")
        assert response.status_code == 404


class TestListBacktestRuns:
    """Test list backtest runs endpoint"""

    def test_list_runs_success(self, client, mock_db):
        # Create mock runs
        mock_runs = []
        for i in range(3):
            mock_run = Mock(spec=BacktestRun)
            mock_run.id = i + 1
            mock_run.symbol = "BTCUSDT"
            mock_run.timeframe = "1h"
            mock_run.status = "success"
            mock_run.started_at = datetime(2024, 1, 1, 12, 0, 0)
            mock_run.final_balance = 10000.0 + (i * 1000)
            mock_run.total_return_pct = i * 5.0
            mock_runs.append(mock_run)

        mock_db.query.return_value.count.return_value = 3
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
            mock_runs
        )

        response = client.get("/backtest/runs/list?skip=0&limit=10")
        assert response.status_code == 200
        data = response.json()

        assert data["ok"] is True
        assert data["total"] == 3
        assert len(data["runs"]) == 3

    def test_list_runs_with_filters(self, client, mock_db):
        mock_db.query.return_value.filter.return_value.count.return_value = 1
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
            []
        )

        response = client.get(
            "/backtest/runs/list", params={"status": "success", "symbol": "BTCUSDT"}
        )
        assert response.status_code == 200


class TestValidateBacktest:
    """Test backtest validation endpoint"""

    @patch("src.api.routes_backtest.create_backtest_run")
    @patch("src.api.routes_backtest.run_backtest_for_run_id")
    def test_validate_backtest_success(
        self, mock_run_backtest, mock_create_run, client, temp_features_file
    ):
        # Mock create_backtest_run to return sequential IDs
        mock_create_run.side_effect = [1, 2, 3, 4, 5]

        payload = {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "initial_balance": 10000.0,
            "runs": 5,
            "vary_seed": False,
            "seed": 42,
        }

        response = client.post("/backtest/validate", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["ok"] is True
        assert data["runs_count"] == 5
        assert len(data["run_ids"]) == 5
        assert data["vary_seed"] is False
        assert "batch_id" in data

        # Verify create_backtest_run was called 5 times
        assert mock_create_run.call_count == 5

    @patch("src.api.routes_backtest.create_backtest_run")
    @patch("src.api.routes_backtest.run_backtest_for_run_id")
    def test_validate_backtest_vary_seed(
        self, mock_run_backtest, mock_create_run, client, temp_features_file
    ):
        mock_create_run.side_effect = [1, 2, 3]

        payload = {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "initial_balance": 10000.0,
            "runs": 3,
            "vary_seed": True,
            "seed": 100,
        }

        response = client.post("/backtest/validate", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["vary_seed"] is True


class TestCompareBacktestRuns:
    """Test compare backtest runs endpoint"""

    def test_compare_runs_success_reproducible(self, client, mock_db):
        # Create identical mock runs
        mock_runs = []
        for i in range(3):
            mock_run = Mock(spec=BacktestRun)
            mock_run.id = i + 1
            mock_run.status = "success"
            mock_run.seed = 42
            mock_run.final_balance = 11000.0  # Same for all
            mock_run.total_return_pct = 10.0  # Same for all
            mock_run.max_drawdown_pct = -5.0
            mock_run.trades_count = 50  # Same for all
            mock_run.notes = None
            mock_runs.append(mock_run)

        mock_db.query.return_value.filter.return_value.all.return_value = mock_runs

        payload = {"run_ids": [1, 2, 3]}
        response = client.post("/backtest/validate/compare", json=payload)

        assert response.status_code == 200
        data = response.json()

        assert data["ok"] is True
        assert data["ready"] is True
        assert data["reproducible"] is True
        assert data["successful_runs"] == 3
        assert len(data["items"]) == 3
        assert "statistics" in data

    def test_compare_runs_not_ready(self, client, mock_db):
        # Create runs with mixed status
        mock_run1 = Mock(spec=BacktestRun)
        mock_run1.id = 1
        mock_run1.status = "success"

        mock_run2 = Mock(spec=BacktestRun)
        mock_run2.id = 2
        mock_run2.status = "running"
        mock_run2.started_at = datetime(2024, 1, 1, 12, 0, 0)

        mock_db.query.return_value.filter.return_value.all.return_value = [
            mock_run1,
            mock_run2,
        ]

        payload = {"run_ids": [1, 2]}
        response = client.post("/backtest/validate/compare", json=payload)

        assert response.status_code == 200
        data = response.json()

        assert data["ready"] is False

    def test_compare_runs_not_found(self, client, mock_db):
        mock_db.query.return_value.filter.return_value.all.return_value = []

        payload = {"run_ids": [999, 1000]}
        response = client.post("/backtest/validate/compare", json=payload)

        assert response.status_code == 404

    def test_compare_runs_variance_detected(self, client, mock_db):
        # Create runs with different results
        mock_run1 = Mock(spec=BacktestRun)
        mock_run1.id = 1
        mock_run1.status = "success"
        mock_run1.seed = 42
        mock_run1.final_balance = 11000.0
        mock_run1.total_return_pct = 10.0
        mock_run1.max_drawdown_pct = -5.0
        mock_run1.trades_count = 50
        mock_run1.notes = None

        mock_run2 = Mock(spec=BacktestRun)
        mock_run2.id = 2
        mock_run2.status = "success"
        mock_run2.seed = 43
        mock_run2.final_balance = 10500.0  # Different
        mock_run2.total_return_pct = 5.0  # Different
        mock_run2.max_drawdown_pct = -3.0
        mock_run2.trades_count = 45  # Different
        mock_run2.notes = None

        mock_db.query.return_value.filter.return_value.all.return_value = [
            mock_run1,
            mock_run2,
        ]

        payload = {"run_ids": [1, 2]}
        response = client.post("/backtest/validate/compare", json=payload)

        assert response.status_code == 200
        data = response.json()

        assert data["reproducible"] is False


class TestDeleteBacktestRun:
    """Test delete backtest run endpoint"""

    def test_delete_run_success(self, client, mock_db):
        mock_run = Mock(spec=BacktestRun)
        mock_run.id = 1

        mock_db.query.return_value.filter.return_value.first.return_value = mock_run

        response = client.delete("/backtest/1")
        assert response.status_code == 200
        data = response.json()

        assert data["ok"] is True
        mock_db.delete.assert_called_once_with(mock_run)
        mock_db.commit.assert_called_once()

    def test_delete_run_not_found(self, client, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None

        response = client.delete("/backtest/999")
        assert response.status_code == 404


# Integration test example
class TestBacktestIntegration:
    """Integration tests for full backtest workflow"""

    @pytest.mark.integration
    @patch("src.api.routes_backtest.create_backtest_run")
    @patch("src.api.routes_backtest.run_backtest_for_run_id")
    def test_full_backtest_workflow(
        self, mock_run_backtest, mock_create_run, client, temp_features_file, mock_db
    ):
        """Test the complete workflow: create, run, poll, get results"""

        # Step 1: Start a backtest
        mock_create_run.return_value = 1

        payload = {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "initial_balance": 10000.0,
            "seed": 42,
        }

        response = client.post("/backtest/run", json=payload)
        assert response.status_code == 200
        run_id = response.json()["run_id"]

        # Step 2: Poll for results (simulate completed run)
        mock_run = Mock(spec=BacktestRun)
        mock_run.id = run_id
        mock_run.symbol = "BTCUSDT"
        mock_run.timeframe = "1h"
        mock_run.status = "success"
        mock_run.started_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_run.finished_at = datetime(2024, 1, 1, 13, 0, 0)
        mock_run.initial_balance = 10000.0
        mock_run.final_balance = 11500.0
        mock_run.total_return_pct = 15.0
        mock_run.max_drawdown_pct = -5.0
        mock_run.trades_count = 50
        mock_run.notes = None

        mock_db.query.return_value.filter.return_value.first.return_value = mock_run

        response = client.get(f"/backtest/{run_id}")
        assert response.status_code == 200
        data = response.json()

        assert data["run"]["status"] == "success"
        assert data["run"]["final_balance"] == 11500.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
