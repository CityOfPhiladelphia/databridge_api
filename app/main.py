from asyncio import create_task
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import baggage, context, propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.propagators import (
    ResponsePropagator,
    default_setter,
    set_global_response_propagator,
)
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import ValidationError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import yarl

from .internal import internal_router
from .public import ROOT_PATH, public_prefix, public_router
from .utils.models import Error, Links, Meta, ReturnJson
from .utils.utils import (
    api_manager,
    description,
    schema_cache,
    session_manager,
)
from .utils.utils_models import app_version


class OtelResponsePropagator(ResponsePropagator):
    """Propagator that injects OpenTelemetry context headers (such as
    traceparent, tracestate, baggage) and traceresponse into HTTP responses."""

    def inject(
        self,
        carrier,
        context: context.Context | None = None,
        setter=default_setter,
    ) -> None:
        active_baggage = baggage.get_all()
        if context is not None and active_baggage:
            for key, value in active_baggage.items():
                context = baggage.set_baggage(key, value, context=context)
        propagate.inject(carrier, context=context, setter=setter)
        span = trace.get_current_span(context)
        span_context = span.get_span_context()
        if span_context != trace.INVALID_SPAN_CONTEXT:
            setter.set(
                carrier,
                "traceresponse",
                f"00-{trace.format_trace_id(span_context.trace_id)}-{trace.format_span_id(span_context.span_id)}-{span_context.trace_flags:02x}",
            )


def sanitize_aiohttp_url(url: yarl.URL) -> str:
    """Redact sensitive tokens from outgoing aiohttp request URLs in spans."""
    if "token" in url.query:
        url = url.update_query({"token": "********"})
    return str(url)


def setup_opentelemetry(app: FastAPI) -> None:
    """Configure OpenTelemetry tracing, propagation, and instrumentation for
    FastAPI and outgoing aiohttp backend requests."""
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "databridge-api")
    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: app_version,
        }
    )
    tracer_provider = TracerProvider(resource=resource)

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
    )
    if otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(tracer_provider)
    set_global_response_propagator(OtelResponsePropagator())

    AioHttpClientInstrumentor().instrument(
        tracer_provider=tracer_provider,
        url_filter=sanitize_aiohttp_url,
    )
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        exclude_spans=["receive", "send"],
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

app = FastAPI(
    lifespan=lifespan,
    title="Databridge API",
    description=description,
    version = app_version, 
    docs_url=None,
    redoc_url=None,
    openapi_url=f"{public_prefix}/openapi.json",
    root_path=ROOT_PATH
)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.include_router(internal_router)
app.include_router(public_router)
revise_openapi_paths()
setup_opentelemetry(app)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Overwrite default FastAPI Validation Error to return consistent with JSON:API Spec"""
    links = Links(self=str(request.url))
    rv_combined = ReturnJson(links=links, errors=[], meta=Meta())
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
    try: 
        links = Links(self=str(request.url))
    except ValidationError: 
        links = Links()
    error = Error(code=exc.status_code, title=exc.headers["title"], detail=exc.detail)
    rv = ReturnJson(links=links, errors=[error], meta=Meta())
    response = JSONResponse(
        status_code=exc.status_code,
        content=rv.model_dump(mode="json", exclude_none=True),
    )
    return response
