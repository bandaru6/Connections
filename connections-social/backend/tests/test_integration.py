import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_graph_summary():
    response = client.get("/graph/summary")
    assert response.status_code == 200
    data = response.json()
    assert "persons_total" in data
    assert "known_persons_total" in data
    assert "unknown_persons_total" in data
    assert "edges_total" in data
    
    # Check consistency
    # Note: persons_total depends on include_unknown default (False)
    # So persons_total should equal known_persons_total
    assert data["persons_total"] == data["known_persons_total"]

def test_graph_summary_include_unknown():
    response = client.get("/graph/summary?include_unknown=true")
    assert response.status_code == 200
    data = response.json()
    
    # Check consistency
    assert data["persons_total"] == data["known_persons_total"] + data["unknown_persons_total"]

def test_graph_neighbors():
    # Use a known person from baseline (Barack Obama)
    # Only test if data exists (baseline confirmed it does)
    response = client.get("/graph/neighbors?person=Barack%20Obama")
    if response.status_code == 404:
        pytest.skip("Barack Obama not found in graph")
    
    assert response.status_code == 200
    data = response.json()
    assert data["person"] == "Barack Obama"
    assert len(data["neighbors"]) > 0
    
    neighbor = data["neighbors"][0]
    # Verify schema keys
    assert "neighbor" in neighbor
    assert "weight" in neighbor
    assert "evidence" in neighbor

def test_persons_list():
    response = client.get("/graph/persons/list")
    assert response.status_code == 200
    data = response.json()
    assert "persons" in data
    assert data["count"] == len(data["persons"])
    
    # Check if Barack Obama is in the list (if graph populated)
    if data["count"] > 0:
        # Check unknown filter (default False)
        for person in data["persons"]:
            assert not person.startswith("UNKNOWN_")

def test_persons_list_include_unknown():
    response = client.get("/graph/persons/list?include_unknown=true")
    assert response.status_code == 200
    data = response.json()
    
    # If we have results
    if data["count"] > 0:
         # We can't guarantee unknowns exist unless we controlled ingest, 
         # but we can check the request didn't fail
         pass

def test_graph_ego():
    response = client.get("/graph/ego?person=Barack%20Obama&depth=2")
    if response.status_code == 404:
        pytest.skip("Barack Obama not found")
        
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) > 0

def test_graph_path():
    # Test path between two known connected people
    # From baseline: Barack Obama <-> Donald Trump (weight 1)
    response = client.get("/graph/path?source=Barack%20Obama&target=Donald%20Trump")
    if response.status_code == 404:
        pytest.skip("Persons not found")
        
    assert response.status_code == 200
    data = response.json()
    assert data["found"] is True
    assert data["source"] == "Barack Obama"
    assert data["target"] == "Donald Trump"
    assert len(data["path"]) >= 2
    assert "Donald Trump" in data["path"]
    assert len(data["edges"]) >= 1
