from asyncio import create_task
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

from .internal import internal_router
from .public import public_router, public_prefix
from .utils.models import Error, Links, ReturnJson
from .utils.utils import (
    description,
    schema_cache,
    session_manager,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Define code to run before the FastAPI app starts and after it shuts down,
    namely to initiate the aiohttp session.

    Args:
        app (FastAPI): App
    """
    schema_cache.check_latest_commit()
    commit_check_task = create_task(schema_cache.loop_commit_check())
    await session_manager.start()
    assert schema_cache.cache
    yield
    commit_check_task.cancel()
    await session_manager.stop()


app = FastAPI(
    lifespan=lifespan,
    title="OIT API Data Wrapper",
    description=description,
    docs_url=f"{public_prefix}/docs",
)
app.include_router(internal_router)
app.include_router(public_router)

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
