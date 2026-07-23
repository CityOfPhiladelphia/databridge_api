from collections.abc import Generator
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from .main import app
from .public import public_prefix
from .utils.utils import api_manager
from .utils.utils_tests import generate_ago_token

# Response validation handled by pydantic on API server itself
# Still have to coerce FastAPI default validation errors to JSON:API spec
GOOD_TABLES = [
    "rtt_summary",  # Public, geometric, AGO & Carto. Large enough to crash this API.
    "ppd_complaints",  # Public, non-geometric, AGO & Carto,
]
PRIVATE_TABLE = "city_locations_point"  # Private, geometric, AGO only


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    """Initiate the FastAPI Test Clinet

    Yields:
        TestClient: FastAPI Test Client
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def token() -> str:
    """Get a private token for accessing private AGO datasets

    Returns:
        str: AGO private token
    """
    response_json = generate_ago_token()
    token = response_json["token"]
    return token


################################################################################
# Valid Parameter Tests #
################################################################################


@pytest.mark.parametrize("table", GOOD_TABLES)
@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_valid(client: TestClient, service: str, table: str):
    """Test that each service works"""
    params = {"table": table, "service": service, "max_age": 0}
    response = client.get(f"{public_prefix}/get", params=params)
    rv = response.json()
    assert response.status_code == 200
    assert rv["links"]["self"] == response.url
    assert rv["data"]["features"], f'Service {service} found zero features in table {table}'


@pytest.mark.parametrize("count_only", [True, False])
@pytest.mark.parametrize("service", ["ago"]) # Keeping this as a parameter for easier ID'ing which tests use which APIs
def test_valid_private(client: TestClient, token: str, service: str, count_only: bool):
    """Test that a token passed in can access AGO private data"""
    table = PRIVATE_TABLE
    params = {
        "table": table,
        "limit": 5,
        "count_only": count_only,
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code <= 500

    headers = {"Authorization": f"Bearer {token}"}
    response = client.get(f"{public_prefix}/get", params=params, headers=headers)
    rv = response.json()
    assert response.status_code == 200
    assert rv["links"]["self"] == response.url
    assert "********" in rv["meta"]["service_url"]
    if 'records_total' in rv['meta']: 
        assert rv["meta"]["records_total"] > 0, f"Service {service} found zero features in table {table}"
    elif 'record_count' in rv['meta']: 
        assert rv["meta"]["record_count"] > 0, f"Service {service} found zero features in table {table}"


@pytest.mark.parametrize("service", ["carto", "databridge"])
def test_valid_private_no_interfere(client: TestClient, service: str, token: str):
    """Test that a private token doesn't interfere with other APIs"""
    table = GOOD_TABLES[0]
    params = {"table": table, "limit": 5, "service": service, "max_age": 0}
    response = client.get(
        f"{public_prefix}/get", params=params, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    rv = response.json()
    assert rv["data"]["features"], f'Service {service} found zero features in table {table}'


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_valid_fields(client: TestClient, service: str):
    """Test that the `fields` parameter returns only those fields"""
    table = GOOD_TABLES[0]
    params = {
        "table": table,
        "limit": 2,
        "fields": "objectid,document_id,document_type,display_date",
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code == 200
    rv = response.json()
    data = rv["data"]
    for feature in data["features"]:
        assert set(feature["properties"].keys()) == set(params["fields"].split(","))
    assert rv["data"]["features"], f'Service {service} found zero features in table {table}'
    

@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_valid_fields2(client: TestClient, service: str):
    params = {
        "table": GOOD_TABLES[0],
        "limit": 2,
        "fields": "document_id,document_type,display_date",
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code == 200
    rv = response.json()
    data = rv["data"]
    for feature in data["features"]:
        assert set(feature["properties"].keys()) == set(params["fields"].split(","))


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_valid_where(client: TestClient, service: str):
    """Test that the `where` parameter works"""
    table = GOOD_TABLES[1]
    params = {
        "table": table,
        "where": "objectid <= 2",
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    rv = response.json()
    assert response.status_code == 200
    assert rv["meta"]["record_count"] == 2
    assert len(rv["data"]["features"]) == 2
    assert rv["data"]["features"], f'Service {service} found zero features in table {table}'


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_valid_where_parenthesization(client: TestClient, service: str):
    """Test that the `where` clause given by the next url and joined with an SQL
    AND doesn't decouple any existing WHERE clause, i.e. because SQL `AND` binds
    more tightly than `OR`"""
    LIMIT = 2
    table = GOOD_TABLES[1]
    params = {
        "table": table,
        "where": "objectid >= 1 OR objectid >= 3",
        "limit": LIMIT,
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    rv = response.json()
    assert response.status_code == 200
    next_url = rv["links"]["next"]
    assert rv["data"]["features"], f'Service {service} found zero features in table {table}'

    response2 = client.get(next_url)
    rv2 = response2.json()
    rv2_first_objectid = int(rv2["data"]["features"][0]["id"])
    assert rv2_first_objectid >= LIMIT
    assert rv2["data"]["features"], f'Service {service} found zero features in table {table}'


@pytest.mark.parametrize("table", [GOOD_TABLES[0]])
@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_valid_limit_next(client: TestClient, service: str, table: str):
    """Test that the `limit` parameter works and that the `next` url works"""
    LIMIT = 2
    params = {"table": table, "limit": LIMIT, "service": service, "max_age": 0}
    response = client.get(f"{public_prefix}/get", params=params)
    rv = response.json()
    assert response.status_code == 200
    assert rv["data"]["features"], f'Service {service} found zero features in table {table}'
    data = rv["data"]
    ids = [feature["id"] for feature in data["features"]]
    max_id = max(ids)
    assert rv["meta"]["record_count"] == LIMIT
    assert len(rv["data"]["features"]) == LIMIT

    next_url = rv["links"]["next"]
    response2 = client.get(next_url)
    assert response2.status_code == 200
    rv2 = response2.json()
    assert rv2["data"]["features"], f'Service {service} found zero features in table {table}'
    data2 = rv2["data"]
    ids2 = [feature["id"] for feature in data2["features"]]
    assert rv2["meta"]["record_count"] == LIMIT
    assert len(rv2["data"]["features"]) == LIMIT
    for id2 in ids2:
        assert id2 > max_id


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_valid_count_only(client: TestClient, service: str):
    """Test that the `count_only` parameter works"""
    table = GOOD_TABLES[1]
    params = {
        "table": table,
        "fields": "whatever,whatever",  # Should have no effect
        "limit": 3,  # Should have no effect
        "count_only": "true",
        "where": "objectid <= 5",
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code == 200
    rv = response.json()
    assert rv["meta"]["records_total"] == 5


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_valid_srid(client: TestClient, service: str):
    """Test that the `srid` parameter works"""
    table = GOOD_TABLES[0]
    params = {
        "table": table,
        "limit": 2,
        "out_sr": 4326,
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    rv = response.json()
    assert response.status_code == 200
    data = rv["data"]
    assert rv["data"]["features"], f'Service {service} found zero features in table {table}'

    params["out_sr"] = 2272
    response2 = client.get(f"{public_prefix}/get", params=params)
    rv2 = response2.json()
    assert response2.status_code == 200
    data2 = rv2["data"]
    assert data != data2
    assert rv2["data"]["features"], f'Service {service} found zero features in table {table}'


@pytest.mark.parametrize("service", ["ago", "carto", "databridge"])
def test_valid_sql(client: TestClient, service: str):
    """Test that the `sql` parameter works for Carto & Databridge and that it 
    fails correctly for AGO"""
    table = GOOD_TABLES[0]
    params = {
        "table": "ANSTHES",  # Should have no effect
        "fields": "whatever,whatever",  # Should have no effect
        "limit": 3,  # Should have no effect
        "sql": f"SELECT * FROM {table} LIMIT 5",
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    if service == 'ago':
        assert response.status_code >= 400 and response.status_code < 500
        return None
    else: 
        assert response.status_code == 200
        rv = response.json()
        assert rv["meta"]["record_count"] == 5
        assert rv["data"]["features"], f'Service {service} found zero features in table {table}'
        assert "next" not in rv["links"].keys()


@pytest.mark.parametrize("service", ["carto"])
def test_valid_sql_too_large_for_carto(client: TestClient, service: str):
    """Test that the `sql` parameter works will error if the response from Carto
    is too large to handle but smaller than a timeout. This test
    should only run on Carto which has no inherent limits to response data size.
    PostgREST server has a configured limit of 1000 records"""
    params = {
        "sql": f"SELECT * FROM {GOOD_TABLES[0]} LIMIT 50000",
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code == 413


@pytest.mark.parametrize("table", GOOD_TABLES)
@pytest.mark.parametrize("service", [None])
def test_valid_no_service(client: TestClient, table: str, service: None):
    """Test that the API works if no `service` is provided"""
    params = {"table": table, "limit": 1, "max_age": 0}
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code == 200
    rv = response.json()
    assert rv["data"]["features"], f'Service {service} found zero features in table {table}'


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_valid_timeout(client: TestClient, service: str):
    """Test that the API timeout parameter returns the correct error code"""
    params = {
        "table": GOOD_TABLES[0],
        "timeout": 0.001,
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code == 408


def test_valid_harmonized_timestamps(client: TestClient):
    """Test that the data returned from the downstream APIs has the same ISO-8601 
    formatted timestamp values"""
    timestamp_dict = {
        "display_date": None,
        "receipt_date": None,
        "recording_date": None,
        "document_date": None,
    }
    for service in api_manager.map_str_to_api.keys(): 
        params = {
            "table": GOOD_TABLES[0],
            "fields": ",".join(timestamp_dict.keys()),
            "service": service,
            "max_age": 0,
            "limit": 1
        }
        response = client.get(f"{public_prefix}/get", params=params)
        assert response.status_code == 200
        data = response.json()
        for field, value in data['data']['features'][0]['properties'].items(): 
            if field in timestamp_dict.keys() and value: 
                assert dt.datetime.fromisoformat(value)
                if timestamp_dict[field]: 
                    assert timestamp_dict[field] == value
                else: 
                    timestamp_dict[field] = value


@pytest.mark.skip("""Skipping this test because these tables have differences 
both in timestamp fields and in geometry fields that are unrelated to this API. 
""")
@pytest.mark.parametrize("table", GOOD_TABLES)
def test_same_response(client: TestClient, table: str):
    """Test that the API timeout parameter returns the correct error code"""
    params = {"table": table, "limit": 1, "max_age": 0}
    ago_params = params | {"service": "ago"}
    carto_params = params | {"service": "carto"}
    ago_response = client.get(f"{public_prefix}/get", params=ago_params)
    carto_response = client.get(f"{public_prefix}/get", params=carto_params)
    assert ago_response.status_code == 200 and carto_response.status_code == 200
    ago_json = ago_response.json()
    ago_properties = ago_json["data"]["features"][0]['properties']
    carto_json = carto_response.json()
    carto_properties = carto_json["data"]["features"][0]['properties']
    base_output = {"d1_only": [], "different": [], "d2_only": []}
    comparison = {"d1_only": [], "different": [], "d2_only": []}
    comparison = compare_dicts(ago_properties, carto_properties, comparison)
    assert comparison == base_output

def compare_dicts(
    d1, d2, output: dict, prefix=""
):
    for key in d1:
        if key not in d2.keys():
            output["d1_only"].append({f"d1.{prefix}{key}": d1[key]})
        elif d1[key] != d2[key]:
            output["different"].append(
                {f"d1.{prefix}{key}": d1[key], f"d2.{prefix}{key}": d2[key]}
            )
    for key in d2:
        if key not in d1.keys():
            output["d2_only"].append({f"d2.{prefix}{key}": d1[key]})
    return output


################################################################################
# Invalid Parameter Tests #
################################################################################

# Note that the invalid parameter tests generally want a response code >= 400 and
# < 500 because any problem in the python code itself would return a 500 error code.
# The API should be well-enough designed that the user never receives
# "Internal Server Error" as that would leave them clueless as to what went wrong.

@pytest.mark.parametrize("service", [None])
def test_invalid_nothing(client: TestClient, service: None):
    """Test that the API fails if no `sql` or `table` parameters passed"""
    response = client.get(f"{public_prefix}/get")
    assert response.status_code >= 400 and response.status_code < 500
    data = response.json()
    assert "errors" in data

@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_invalid_nothing2(client: TestClient, service: str):
    """Test that the API fails if no `sql` or `table` parameters passed"""
    params = {"service": service}
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_invalid_table(client: TestClient, service: str):
    """Test that the API fails if an invalid `table` parameter is passed"""
    params = {"table": "bad_table", "service": service}
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_invalid_fields(client: TestClient, service: str):
    """Test that the API fails if an invalid `fields` parameter is passed"""
    # Note that AGO will run with it if the field is "1234" or "'text' AS example"
    params = {
        "table": GOOD_TABLES[0],
        "fields": "badfield",
        "service": service,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_invalid_where(client: TestClient, service: str):
    """Test that the API fails if an invalid `where` parameter is passed"""
    params = {
        "table": GOOD_TABLES[1],
        "where": "not_a_column <= 2",
        "service": service,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize("limit", ["-1", "abc"])
@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_invalid_limit(client: TestClient, service: str, limit: str):
    """Test that the API fails if an invalid `limit` parameter is passed"""
    params = {
        "table": GOOD_TABLES[0],
        "limit": limit,
        "service": service,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert (
        response.status_code >= 400 and response.status_code <= 500
    )  # Carto returns a 500 error here
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_invalid_count_only(
    client: TestClient,
    service: str,
):
    """Test that the API fails if an invalid `count_only` table is passed"""
    params = {"table": "ASNTEHUSA", "count_only": "true", "service": service}
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_invalid_sql(client: TestClient, service: str):
    """Test that the API fails if invalid `sql` parameter is passed"""
    params = {"sql": "SELECT * FROM ANSTEHUSANTH", "service": service}
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_invalid_sql_ddl_insert(client: TestClient, service: str):
    """Test that the APIs fail if DDL (INSERT/UPDATE) statements are passed"""
    params = {
        "sql": "INSERT INTO PPD_COMPLAINTS (objectid) VALUES (0)",
        "service": service,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code <= 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize("service", api_manager.map_str_to_api.keys())
def test_invalid_sql_ddl_update(client: TestClient, service: str):
    """Test that the APIs fail if DDL (INSERT/UPDATE) statements are passed"""
    params = {
        "sql": "UPDATE PPD_COMPLAINTS SET objectid = 0",
        "service": service,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code <= 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize("service", ["Carto"])
def test_invalid_sql_too_large_for_carto(client: TestClient, service: None):
    """Test that the API fails if too large of a dataset is requsted. This test 
    should only run on Carto which has no inherent limits to response data size. 
    PostgREST server has a configured limit of 1000 records"""
    params = {
        "sql": f"SELECT * FROM {GOOD_TABLES[0]}",
        "service": service,
        "max_age": 0,
    }
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code < 500
    data = response.json()
    assert "errors" in data


@pytest.mark.parametrize("service", [None])
def test_invalid_no_service(client: TestClient, service: None):
    """Test that the API fails if an invalid `table` parameter is passed and no
    `service` is selected"""
    params = {"table": "bad_table", "limit": 1}
    response = client.get(f"{public_prefix}/get", params=params)
    assert response.status_code >= 400 and response.status_code < 500
    data = response.json()
    assert "errors" in data
