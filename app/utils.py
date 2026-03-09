from .models import ReturnJson
from fastapi.responses import JSONResponse

description = """
This wrapper API retrieves data from ArcGIS Online (AGO) and Carto SQL API V3 (Carto) following 
the below specifications: 
1. [JSON:API](https://jsonapi.org/) for API response,
1. [GeoJSON](https://datatracker.ietf.org/doc/html/rfc7946) for returned data, and
1. [OpenAPI](https://www.openapis.org/) for API documentation

### Carto SQL API V3
Carto solely contains public tables, but they 
can only be accessed via a private API token. This token will not be accessible 
to the API user, meaning that the Carto `service_url` will return `HTTP 401 Unauthorized` errors.

### ArcGIS Online
AGO will contain both public and private tables. To access private tables, 
separately generate an access token and then include the token in the following HTTP header: 
```
Authorization: Bearer <token>
```
The AGO `service_url` will mask any bearer authorization token included in the API call, 
meaning this url will not suffice to access the data. If no authorization token was passed 
to the API, then the service url will suffice to access public tables.
"""

def generate_final_response(rv: ReturnJson) -> ReturnJson | JSONResponse: 
    """Return the correct JSON object, either ReturnJson or JSONResponse if
    errors were encountered

    Args:
        rv (ReturnJson): JSON:API spec for returning data

    Returns:
        JSONResponse: FastAPI JSON object with an HTTP Status Code
    """    
    if not rv.errors:
        return rv
    else:
        rv = JSONResponse(
            status_code=int(rv.errors[0].code),
            content=rv.model_dump(mode="json", exclude_none=True),
        )
        return rv
