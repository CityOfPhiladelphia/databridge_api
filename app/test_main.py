from fastapi.testclient import TestClient
import pytest
from .main import app, MAP_STR_TO_API

# Response validation handled by pydantic on API server itself
# Still have to coerce FastAPI default validation errors to JSON:API spec
GOOD_TABLES = [
    'dor_parcel',       # Contains shape data
    'ppd_complaints'    # Does not contain shape data
]

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

@pytest.mark.parametrize('table', GOOD_TABLES)
@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid(client, service: str, table: str):
    params = {'table': table, 'service': service}
    response = client.get('/get', params=params)
    rv = response.json()
    assert response.status_code == 200
    assert rv['links']['self'] == response.url

@pytest.mark.parametrize("table", [GOOD_TABLES[0]])
@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid_limit_next(client, service: str, table: str):
    LIMIT = 2
    params = {'table': table, 'limit': LIMIT, 'service': service}
    response = client.get('/get', params=params)
    rv = response.json()
    assert response.status_code == 200
    data = rv['data']
    ids = [feature['id'] for feature in data['features']]
    max_id = max(ids)
    assert rv['meta']['record_count'] == LIMIT
    assert len(rv['data']['features']) == LIMIT
    
    next_url = rv['links']['next']
    response2 = client.get(next_url)
    assert response2.status_code == 200
    rv2 = response2.json()
    data2 = rv2['data']
    ids2 = [feature['id'] for feature in data2['features']]
    assert rv2['meta']['record_count'] == LIMIT
    assert len(rv2['data']['features']) == LIMIT
    for id2 in ids2: 
        assert id2 > max_id

@pytest.mark.parametrize("table", GOOD_TABLES)
def test_no_service(client, table: str):
    params = {'table': table, 'limit': 1}
    response = client.get('/get', params=params)
    assert response.status_code == 200

@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid_fields(client, service: str):
    params = {
        "table": "TABLE",
        "limit": 2,
        "fields": "objectid,addr_std",
        "service": service,
    }
    response = client.get('/get', params=params)
    rv = response.json()
    data = rv['data']
    assert response.status_code == 200
    for feature in data['features']: 
        assert set(feature['properties'].keys()) == set(params['fields'].split(','))

@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_invalid_table(client, service: str): 
    params = {'table': 'bad_table', 'service': service}
    response = client.get('/get', params=params)
    assert response.status_code >=400 and response.status_code < 500

