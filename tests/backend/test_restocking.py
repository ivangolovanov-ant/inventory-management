"""
Tests for restocking API endpoints.
"""
from datetime import date

import pytest

from mock_data import restocking_orders


@pytest.fixture(autouse=True)
def reset_restocking_orders():
    """Ensure each test starts with an empty in-memory restocking list."""
    restocking_orders.clear()
    yield
    restocking_orders.clear()


@pytest.fixture
def sample_restocking_request():
    """Sample restocking order request body."""
    return {
        "budget": 5000.0,
        "items": [
            {
                "sku": "WDG-001",
                "name": "Industrial Widget Type A",
                "quantity": 100,
                "unit_price": 24.50,
                "lead_time_days": 7,
            },
            {
                "sku": "GSK-203",
                "name": "High-Temperature Gasket",
                "quantity": 200,
                "unit_price": 6.25,
                "lead_time_days": 4,
            },
        ],
    }


class TestDemandForecastFields:
    """Verify demand forecasts expose cost and lead-time data for restocking."""

    def test_forecasts_include_cost_and_lead_time(self, client):
        """Test that every forecast has unit_cost and lead_time_days."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        for forecast in data:
            assert "unit_cost" in forecast
            assert "lead_time_days" in forecast
            assert isinstance(forecast["unit_cost"], (int, float))
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["unit_cost"] > 0
            assert forecast["lead_time_days"] >= 1


class TestRestockingOrdersEndpoints:
    """Test suite for restocking-order endpoints."""

    def test_get_restocking_orders_empty_initially(self, client):
        """Test getting all restocking orders before any are created."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_create_restocking_order_success(self, client, sample_restocking_request):
        """Test creating a restocking order returns 201 with computed fields."""
        response = client.post("/api/restocking-orders", json=sample_restocking_request)
        assert response.status_code == 201

        order = response.json()
        assert "id" in order
        assert "order_number" in order
        assert order["order_number"].startswith("RST-")
        assert order["status"] == "Submitted"
        assert order["budget"] == sample_restocking_request["budget"]
        assert len(order["items"]) == 2

        expected_total = sum(
            i["quantity"] * i["unit_price"] for i in sample_restocking_request["items"]
        )
        assert abs(order["total_value"] - expected_total) < 0.01

    def test_expected_delivery_uses_max_lead_time(self, client):
        """Test that expected_delivery = order_date + max(lead_time_days)."""
        body = {
            "budget": 10000.0,
            "items": [
                {"sku": "A", "name": "A", "quantity": 1, "unit_price": 1.0, "lead_time_days": 3},
                {"sku": "B", "name": "B", "quantity": 1, "unit_price": 1.0, "lead_time_days": 14},
                {"sku": "C", "name": "C", "quantity": 1, "unit_price": 1.0, "lead_time_days": 7},
            ],
        }
        response = client.post("/api/restocking-orders", json=body)
        assert response.status_code == 201

        order = response.json()
        order_date = date.fromisoformat(order["order_date"])
        expected_delivery = date.fromisoformat(order["expected_delivery"])
        assert (expected_delivery - order_date).days == 14

    def test_create_empty_items_returns_400(self, client):
        """Test that an empty items list is rejected."""
        response = client.post(
            "/api/restocking-orders", json={"budget": 1000.0, "items": []}
        )
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "item" in data["detail"].lower()

    def test_created_order_appears_in_list(self, client, sample_restocking_request):
        """Test that a created order is returned by the list endpoint."""
        create_response = client.post(
            "/api/restocking-orders", json=sample_restocking_request
        )
        assert create_response.status_code == 201
        created = create_response.json()

        list_response = client.get("/api/restocking-orders")
        assert list_response.status_code == 200

        data = list_response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == created["id"]
        assert data[0]["order_number"] == created["order_number"]

    def test_restocking_order_item_structure(self, client, sample_restocking_request):
        """Test that returned items have proper structure and types."""
        response = client.post("/api/restocking-orders", json=sample_restocking_request)
        assert response.status_code == 201

        order = response.json()
        for item in order["items"]:
            assert "sku" in item
            assert "name" in item
            assert "quantity" in item
            assert "unit_price" in item
            assert "lead_time_days" in item
            assert isinstance(item["quantity"], int)
            assert isinstance(item["unit_price"], (int, float))
            assert isinstance(item["lead_time_days"], int)
