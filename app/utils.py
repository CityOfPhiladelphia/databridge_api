from .abstract_worker import ReturnJson
from fastapi.responses import JSONResponse

description = """
This wrapper API retrieves data from ArcGIS Online and Carto SQL API V3 following the below specifications: 
1. [JSON:API](https://jsonapi.org/) for API response,
1. [GeoJSON](https://datatracker.ietf.org/doc/html/rfc7946) for returned data, and
1. [OpenAPI](https://www.openapis.org/) for API documentation
"""

def generate_final_response(rv: ReturnJson) -> JSONResponse: 
    if not rv.errors:
        return rv
    else:
        rv = JSONResponse(
            status_code=int(rv.errors[0].code),
            content=rv.model_dump(mode="json", exclude_none=True),
        )
        return rv
