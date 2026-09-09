from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, HttpUrl


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
    self: HttpUrl = None
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


class TableField(BaseModel):
    name: str
    type: str

    model_config = ConfigDict(extra="allow")


class TableSchema(BaseModel):
    fields: list[TableField]
    valid_fields: list[str] = []
    geom_column: str | None = None
    timestamp_fields: list[str] = []

    model_config = ConfigDict(extra="allow")