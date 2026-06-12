from typing import Annotated

from fastapi import APIRouter
from fastapi.exceptions import HTTPException

from .utils.utils import schema_cache

internal_router = APIRouter(include_in_schema=False)


@internal_router.get("/schemas", tags=["Routes"])
async def get_schemas(
    table: Annotated[
        str | None, "Name of table to retrieve",
    ] = None,
) -> dict:
    """Return schema information for debugging purposes. This endpoint is meant to 
    be internally accessible only

    Args:
        table (str, optional): If provided, only return the schema for the specified 
        table if it exists. Defaults to None, in which case all schemas are returned.

    Returns:
        dict: Information about the schema cache
    """    
    rv = {
        "latest_check": schema_cache.latest_check,
        "latest_update": schema_cache.latest_update,
        "commit_check_delay_seconds": schema_cache.commit_check_delay,
        "folder": schema_cache.folder,
        "latest_repo_target": schema_cache.latest_repo_target,
        "invalid_fields": schema_cache.invalid_fields,
        "schema_count": len(schema_cache.cache.keys())
    }
    if table:
        table = table.lower()
        try:
            rv['schema'] = {table: schema_cache.cache[table]}
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"The requested schema '{table}' was not found",
                headers={"title": "Not Found"},
            )
    else:
        rv["schemas"] = schema_cache.cache

    return rv
