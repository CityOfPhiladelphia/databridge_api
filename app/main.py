from asyncio import create_task
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

from .internal import internal_router
from .public import public_prefix, public_router
from .utils.models import Error, Links, ReturnJson
from .utils.utils import (
    api_manager,
    description,
    retrieve_api_version,
    schema_cache,
    session_manager,
)


def revise_openapi_paths(): 
    """Revise the URL paths in the OpenAPI docs to remove the public path prefix. The 
    plan is to host this App behind a reverse proxy and only allow public access 
    to the public endpoints covered by the Public Prefix (currently "/api"). Because 
    this directory will be the root for the reverse proxy and users will not know this,
    the URL paths need to remove the public prefix. 
    """    
    app.openapi()
    revised_openapi_paths = {}
    openapi_paths = app.openapi_schema["paths"]
    for path in openapi_paths:
        if path.startswith(public_prefix):
            new_path = path.removeprefix(public_prefix)
            revised_openapi_paths[new_path] = openapi_paths[path]
    app.openapi_schema["paths"] = revised_openapi_paths


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Define code to run before the FastAPI app starts and after it shuts down,
    including to: 
    1. Run a background async task to update the schemas repository
    1. Run a background async task to reorder the API priority queue
    1. Start/stop the aiohttp session.

    Args:
        app (FastAPI): App
    """
    schema_cache.check_latest_commit()
    commit_check_task = create_task(schema_cache.loop_commit_check())
    reorder_priority_queue_task = create_task(api_manager.reorder_priority_queue())
    await session_manager.start()
    assert schema_cache.cache

    yield

    commit_check_task.cancel()
    reorder_priority_queue_task.cancel()
    await session_manager.stop()


app_version = retrieve_api_version()
app = FastAPI(
    lifespan=lifespan,
    title="Databridge API",
    description=description,
    docs_url=f"{public_prefix}/docs",
    version = app_version
)
app.include_router(internal_router)
app.include_router(public_router)
revise_openapi_paths()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Overwrite default FastAPI Validation Error to return consistent with JSON:API Spec"""
    links = Links(self=str(request.url))
    rv_combined = ReturnJson(links=links, errors=[])
    for err in exc.errors():
        error = Error(
            code="422",
            title=err["type"],
            detail=f"Message: {err['msg']}. Location: {err['loc']}. Input: '{err['input']}'",
        )
        rv_combined.errors.append(error)
    response = JSONResponse(
        status_code=422,
        content=rv_combined.model_dump(mode="json", exclude_none=True),
    )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Overwrite default FastAPI HTTP Error to return consistent with JSON:API Spec"""
    links = Links(self=str(request.url))
    error = Error(code=exc.status_code, title=exc.headers["title"], detail=exc.detail)
    rv = ReturnJson(links=links, errors=[error])
    response = JSONResponse(
        status_code=exc.status_code,
        content=rv.model_dump(mode="json", exclude_none=True),
    )
    return response
