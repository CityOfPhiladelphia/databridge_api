from fastapi.testclient import TestClient
import pytest
import citygeo_secrets as cgs
from .main import app, MAP_STR_TO_API
from .utils_tests import generate_ago_token, AGO_SECRET
from collections.abc import Generator

# Response validation handled by pydantic on API server itself
# Still have to coerce FastAPI default validation errors to JSON:API spec
GOOD_TABLES = [
    'dor_parcel',                       # Public, geometric, AGO & Carto
    'ppd_complaints'                    # Public, non-geometric, AGO & Carto, 
]
PRIVATE_TABLE = 'city_locations_point'  # Private, geometric, AGO only


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    """Initiate the FastAPI Test Clinet

    Yields:
        TestClient: FastAPI Test Client
    """    
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope='module')
def token() -> str: 
    """Get a private token for accessing private AGO datasets

    Returns:
        str: AGO private token
    """    
    response_json = cgs.connect_with_secrets(generate_ago_token, AGO_SECRET)
    token = response_json['token']
    return token

################################################################################
# Valid Parameter Tests # 
################################################################################

@pytest.mark.parametrize('table', GOOD_TABLES)
@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid(client: TestClient, service: str, table: str):
    '''Test that each service works'''
    params = {'table': table, 'service': service}
    response = client.get('/get', params=params)
    rv = response.json()
    assert response.status_code == 200
    assert rv['links']['self'] == response.url


@pytest.mark.parametrize('count_only', [True, False])
def test_valid_private(client: TestClient, token: str, count_only: bool):
    '''Test that a token passed in can access AGO private data'''
    params = {'table': PRIVATE_TABLE, 'limit': 5, 'count_only': count_only, 'service': 'ago'}
    response = client.get("/get", params=params)
    assert response.status_code >= 400 and response.status_code <= 500

    headers={"Authorization": f"Bearer {token}"}
    response = client.get("/get", params=params, headers=headers)
    rv = response.json()
    assert response.status_code == 200
    assert rv['links']['self'] == response.url
    assert '********' in rv['meta']['service_url']


def test_valid_private_no_intefere(client: TestClient, token: str): 
    '''Test that a private token doesn't interfere with other APIs'''
    params = {'table': GOOD_TABLES[0], 'limit': 5, 'service': 'carto'}
    response = client.get(
        "/get", params=params, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200


@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid_fields(client: TestClient, service: str):
    '''Test that the `fields` parameter returns only those fields'''
    params = {
        "table": GOOD_TABLES[0],
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


@pytest.mark.skip('''Skipping this test because if user does not request the "objectid" 
field and this API doesn't include it, then AGO will not provide feature IDs. 
I'm making the design decision to include an extra field in the user response 
rather than not providing the "id" column. Either way, AGO (and thus this API) 
violates the JSON:API spec.''')
@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid_fields2(client: TestClient, service: str):
    params = {
        "table": GOOD_TABLES[0],
        "limit": 2,
        "fields": "addr_std",
        "service": service,
    }
    response = client.get('/get', params=params)
    rv = response.json()
    data = rv['data']
    assert response.status_code == 200
    for feature in data['features']: 
        assert set(feature['properties'].keys()) == set(params['fields'].split(','))


@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid_where(client: TestClient, service: str):
    '''Test that the `where` parameter works'''
    params = {
        "table": GOOD_TABLES[1],
        "where": "objectid <= 2",
        "service": service,
    }
    response = client.get('/get', params=params)
    rv = response.json()
    assert response.status_code == 200
    assert rv['meta']['record_count'] == 2
    assert len(rv['data']['features']) == 2


@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid_where_parethesization(client: TestClient, service: str):
    '''Test that the `where` clause given by the next url and joined with an SQL 
    AND doesn't decouple any existing WHERE clause, i.e. because SQL `AND` binds 
    more tightly than `OR`'''
    LIMIT = 2
    params = {
        "table": GOOD_TABLES[1],
        "where": "objectid >= 1 OR objectid >= 3",
        "limit": LIMIT, 
        "service": service,
    }
    response = client.get('/get', params=params)
    rv = response.json()
    assert response.status_code == 200
    next_url = rv['links']['next']

    response2 = client.get(next_url)
    rv2 = response2.json()
    rv2_first_objectid = int(rv2["data"]["features"][0]['id'])
    assert rv2_first_objectid >= LIMIT


@pytest.mark.parametrize("table", [GOOD_TABLES[0]])
@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid_limit_next(client: TestClient, service: str, table: str):
    '''Test that the `limit` parameter works and that the `next` url works'''
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


@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid_count_only(client: TestClient, service: str):
    '''Test that the `count_only` parameter works'''
    params = {
        "table": GOOD_TABLES[1],
        "fields": "whatever,whatever", # Should have no effect
        "limit": 3,                    # Should have no effect
        "count_only": "true",
        "where": "objectid <= 5",
        "service": service,
    }
    response = client.get('/get', params=params)
    assert response.status_code == 200
    rv = response.json()
    assert rv["meta"]["records_total"] == 5


@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_valid_srid(client: TestClient, service: str):
    '''Test that the `srid` parameter works'''
    params = {
        "table": GOOD_TABLES[0],
        "limit": 2,
        "out_sr": 4326,
        "service": service,
    }
    response = client.get('/get', params=params)
    rv = response.json()
    assert response.status_code == 200
    data = rv['data']
    
    params['out_sr'] = 2272
    response2 = client.get('/get', params=params)
    rv2 = response2.json()
    assert response2.status_code == 200
    data2 = rv2['data']
    assert data != data2


def test_valid_sql(client):
    '''Test that the `sql` parameter works, only on Carto'''
    params = {
        "table": 'ANSTHES',            # Should have no effect
        "fields": "whatever,whatever", # Should have no effect
        "limit": 3,                    # Should have no effect
        "sql": "SELECT * FROM dor_parcel LIMIT 5",
        "service": 'carto',
    }
    response = client.get('/get', params=params)
    assert response.status_code == 200
    data = response.json()
    assert data['meta']['record_count'] == 5


@pytest.mark.parametrize("table", GOOD_TABLES)
def test_valid_no_service(client: TestClient, table: str):
    '''Test that the API works if no `service` is provided'''
    params = {'table': table, 'limit': 1}
    response = client.get('/get', params=params)
    assert response.status_code == 200

################################################################################
# Invalid Parameter Tests # 
################################################################################

def test_invalid_nothing(client):
    '''Test that the API fails if no `sql` or `table` parameters passed''' 
    response = client.get('/get')
    assert response.status_code >=400 and response.status_code < 500
    data = response.json()
    assert 'errors' in data


def test_invalid_nothing2(client):
    '''Test that the API fails if no `sql` or `table` parameters passed''' 
    params = {'service': 'ago'}
    response = client.get('/get', params=params)
    assert response.status_code >=400 and response.status_code < 500
    data = response.json()
    assert 'errors' in data


@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_invalid_table(client: TestClient, service: str):
    '''Test that the API fails if an invalid `table` parameter is passed''' 
    params = {'table': 'bad_table', 'service': service}
    response = client.get('/get', params=params)
    assert response.status_code >=400 and response.status_code < 500
    data = response.json()
    assert 'errors' in data


@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_invalid_fields(client: TestClient, service: str):
    '''Test that the API fails if an invalid `fields` parameter is passed''' 
    # Note that AGO will run with it if the field is "1234" or "'text' AS example"
    params = {
        "table": GOOD_TABLES[0],
        "fields": "badfield",
        "service": service,
    }
    response = client.get('/get', params=params)
    assert response.status_code >=400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_invalid_where(client: TestClient, service: str):
    """Test that the API fails if an invalid `where` parameter is passed"""
    params = {
        "table": GOOD_TABLES[1],
        "where": "not_a_column <= 2",
        "service": service,
    }
    response = client.get('/get', params=params)
    assert response.status_code >=400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize('limit', ["-1", "abc"])
@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_invalid_limit(client: TestClient, service: str, limit: str):
    """Test that the API fails if an invalid `limit` parameter is passed"""
    params = {
        "table": GOOD_TABLES[0],
        "limit": limit,
        "service": service,
    }
    response = client.get('/get', params=params)
    assert response.status_code >=400 and response.status_code <= 500  # Carto returns a 500 error here
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_invalid_count_only(client: TestClient, service: str, ):
    """Test that the API fails if an invalid `count_only` table is passed"""
    params = {
        "table": 'ASNTEHUSA',
        "count_only": 'true',
        'service': service
    }
    response = client.get('/get', params=params)
    assert response.status_code >=400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize('service', MAP_STR_TO_API.keys())
def test_invalid_sql(client: TestClient, service: str):
    """Test that the API fails if invalid `sql` parameter is passed"""
    params = {
        'sql': 'SELECT * FROM ANSTEHUSANTH', 
        'service': service
    }
    response = client.get('/get', params=params)
    assert response.status_code >=400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


def test_invalid_sql_large_payload(client):
    """Test that the API fails if too large of a dataset is requsted"""
    params = {
        'sql': f'SELECT * FROM {GOOD_TABLES[0]}', 
    }
    response = client.get('/get', params=params)
    assert response.status_code == 413
    data = response.json()
    assert "errors" in data


def test_invalid_no_service(client):
    """Test that the API fails if an invalid `table` parameter is passed and no 
    `service` is selected"""
    params = {'table': 'bad_table', 'limit': 1}
    response = client.get('/get', params=params)
    assert response.status_code >=400 and response.status_code < 500
    data = response.json()
    assert "errors" in data
