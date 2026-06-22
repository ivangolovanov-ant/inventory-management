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
    """Sample restocking order request body (sku + quantity only)."""
    return {
        "budget": 5000.0,
        "items": [
            {"sku": "WDG-001", "quantity": 100},
            {"sku": "GSK-203", "quantity": 200},
        ],
    }


def _forecast_by_sku(client):
    """Fetch the demand-forecast catalog keyed by SKU for server-side price lookups."""
    return {f["item_sku"]: f for f in client.get("/api/demand").json()}


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
        """Test creating a restocking order returns 201 with server-derived fields."""
        response = client.post("/api/restocking-orders", json=sample_restocking_request)
        assert response.status_code == 201

        order = response.json()
        assert "id" in order
        assert "order_number" in order
        assert order["order_number"].startswith("RST-")
        assert order["status"] == "Submitted"
        assert order["budget"] == sample_restocking_request["budget"]
        assert len(order["items"]) == 2

        # total_value must be computed from the server's forecast catalog,
        # not from anything the client sent.
        catalog = _forecast_by_sku(client)
        expected_total = sum(
            i["quantity"] * catalog[i["sku"]]["unit_cost"]
            for i in sample_restocking_request["items"]
        )
        assert abs(order["total_value"] - expected_total) < 0.01

    def test_expected_delivery_uses_max_lead_time(self, client):
        """Test that expected_delivery = order_date + max(lead_time_days from catalog)."""
        catalog = _forecast_by_sku(client)
        skus = ["GSK-203", "MTR-304", "WDG-001"]
        expected_max_lead = max(catalog[s]["lead_time_days"] for s in skus)

        body = {
            "budget": 100000.0,
            "items": [{"sku": s, "quantity": 1} for s in skus],
        }
        response = client.post("/api/restocking-orders", json=body)
        assert response.status_code == 201

        order = response.json()
        order_date = date.fromisoformat(order["order_date"])
        expected_delivery = date.fromisoformat(order["expected_delivery"])
        assert (expected_delivery - order_date).days == expected_max_lead

    def test_create_empty_items_returns_400(self, client):
        """Test that an empty items list is rejected."""
        response = client.post(
            "/api/restocking-orders", json={"budget": 1000.0, "items": []}
        )
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "item" in data["detail"].lower()

    def test_unknown_sku_returns_400(self, client):
        """Test that an SKU not present in the forecast catalog is rejected."""
        response = client.post(
            "/api/restocking-orders",
            json={"budget": 1000.0, "items": [{"sku": "NOPE-999", "quantity": 1}]},
        )
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "nope-999" in data["detail"].lower()

    def test_non_positive_quantity_returns_422(self, client):
        """Test that quantity <= 0 fails request validation."""
        for qty in (0, -5):
            response = client.post(
                "/api/restocking-orders",
                json={"budget": 1000.0, "items": [{"sku": "WDG-001", "quantity": qty}]},
            )
            assert response.status_code == 422

    def test_total_exceeds_budget_returns_400(self, client):
        """Test that the server enforces total_value <= budget."""
        catalog = _forecast_by_sku(client)
        sku = "WDG-001"
        unit_cost = catalog[sku]["unit_cost"]
        # Request 10 units but provide budget for only ~1
        response = client.post(
            "/api/restocking-orders",
            json={"budget": unit_cost, "items": [{"sku": sku, "quantity": 10}]},
        )
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "budget" in data["detail"].lower()

    def test_client_supplied_price_is_ignored(self, client):
        """Test that unit_price in the request body is ignored in favour of catalog."""
        catalog = _forecast_by_sku(client)
        response = client.post(
            "/api/restocking-orders",
            json={
                "budget": 100000.0,
                "items": [{"sku": "WDG-001", "quantity": 1, "unit_price": 0.01}],
            },
        )
        assert response.status_code == 201

        order = response.json()
        assert abs(order["items"][0]["unit_price"] - catalog["WDG-001"]["unit_cost"]) < 0.01
        assert abs(order["total_value"] - catalog["WDG-001"]["unit_cost"]) < 0.01

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
