from pydantic import BaseModel, HttpUrl, BeforeValidator
from typing import Annotated


class GeoJsonGeometry(BaseModel):
    """GeoJSON Feature Geometry""" 
    type: str
    coordinates: list


class GeoJsonFeature(BaseModel): 
    """GeoJSON Feature"""
    type: str = 'Feature'
    id: Annotated[str, BeforeValidator(str)] | None = None
    properties: dict
    geometry: GeoJsonGeometry | None = None


class GeoJsonFeatureCollection(BaseModel):
    """GeoJSON Feature Collection""" 
    type: str = 'FeatureCollection'
    features: list[GeoJsonFeature]


class Error(BaseModel): 
    """JSON:API spec for returning errors"""
    code: Annotated[str, BeforeValidator(str)]
    title: str = None
    detail: str = None


class Links(BaseModel, validate_assignment=True): 
    """JSON:API spec for returning URLs"""
    self: HttpUrl
    next: HttpUrl = None


class Meta(BaseModel, validate_assignment=True): 
    """Additional information generated for the user"""
    service: str
    service_url: HttpUrl = None
    service_available_query_parameters: list[str] = None
    record_count: int = None
    records_total: int = None


class ReturnJson(BaseModel, validate_assignment=True): 
    """JSON:API spec for returning data"""
    data: GeoJsonFeatureCollection = None # Either data or errors should be returned
    errors: list[Error] = None
    links: Links = None
    meta: Meta = None
