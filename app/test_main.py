from fastapi.testclient import TestClient
import pytest
from .main import app, MAP_STR_TO_API

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_read_main(client):
    response = client.get("/")
    assert response.status_code == 200

@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid(client, service: str):
    params = {'table': 'dor_parcel', 'limit': 10, 'service': service}
    response = client.get('/get', params=params)
    assert response.status_code == 200

@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_invalid(client, service: str): 
    params = {'table': 'bad_table', 'service': service}
    response = client.get('/get', params=params)
    assert response.status_code >=400 and response.status_code < 500

