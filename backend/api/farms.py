# Paste contents from the generated api/farms.py here
# backend/api/farms.py
"""
Farm CRUD routes.

POST   /farms              — register a new farm (polygon + crop)
GET    /farms              — list all active farms for current user
GET    /farms/{farm_id}    — single farm detail
DELETE /farms/{farm_id}    — soft delete (sets active=False)

Polygon handling:
    The frontend sends a GeoJSON Feature or FeatureCollection from
    leaflet-draw. We accept either format, extract the first Polygon
    geometry, and store it as a PostGIS GEOMETRY(POLYGON, 4326).

    Centroid, area_ha, and district are computed server-side using
    PostGIS functions so the client never has to send them.

    PostGIS SQL used:
        ST_GeomFromGeoJSON(...)       — parse GeoJSON → geometry
        ST_Centroid(boundary)         — centroid point
        ST_Y / ST_X                   — extract lat/lon from point
        ST_Area(boundary::geography)  — area in m², /10000 → ha

Why server-side geometry computation:
    1. Correct: ST_Area in ::geography projection is geodetically accurate.
    2. Safe: client can't inject fake centroid / area.
    3. Automatic district detection uses centroid from DB, not client.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from geoalchemy2.functions import ST_Area, ST_AsGeoJSON, ST_Centroid, ST_GeomFromGeoJSON, ST_X, ST_Y
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import UserTokenData, get_current_user
from db_models.farm import Farm
from services.ml_bridge import detect_district

router = APIRouter(prefix="/farms", tags=["farms"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class FarmCreateRequest(BaseModel):
    name:             str  = Field(..., min_length=1, max_length=100, examples=["Ramesh ka khet"])
    crop:             str  = Field(..., pattern="^(Wheat|Rice)$", examples=["Wheat"])
    boundary_geojson: dict = Field(..., description="GeoJSON Feature or Geometry with Polygon type")

    @field_validator("boundary_geojson")
    @classmethod
    def validate_geojson(cls, v: dict) -> dict:
        """Accepts Feature, FeatureCollection, or bare Geometry."""
        geo_type = v.get("type")
        if geo_type == "FeatureCollection":
            features = v.get("features", [])
            if not features:
                raise ValueError("FeatureCollection has no features.")
            v = features[0]
            geo_type = v.get("type")
        if geo_type == "Feature":
            v = v.get("geometry", {})
            geo_type = v.get("type")
        if geo_type != "Polygon":
            raise ValueError(
                f"Expected a Polygon geometry, got '{geo_type}'. "
                "Draw a closed polygon on the map."
            )
        return v  # always returns a bare Geometry dict


class FarmResponse(BaseModel):
    id:             str
    name:           str
    crop:           str
    centroid_lat:   Optional[float]
    centroid_lon:   Optional[float]
    area_ha:        Optional[float]
    district:       Optional[str]
    gee_extracted:  bool
    active:         bool
    boundary_geojson: Optional[dict] = None
    created_at:     str


class FarmListResponse(BaseModel):
    farms: list[FarmResponse]
    total: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _farm_to_response(farm: Farm, boundary_json: Optional[str] = None) -> FarmResponse:
    return FarmResponse(
        id            = str(farm.id),
        name          = farm.name,
        crop          = farm.crop,
        centroid_lat  = farm.centroid_lat,
        centroid_lon  = farm.centroid_lon,
        area_ha       = round(farm.area_ha, 4) if farm.area_ha else None,
        district      = farm.district,
        gee_extracted = farm.gee_extracted,
        active        = farm.active,
        boundary_geojson = json.loads(boundary_json) if boundary_json else None,
        created_at    = farm.created_at.isoformat(),
    )


async def _get_farm_or_404(farm_id: UUID, user_id: UUID, db: AsyncSession) -> Farm:
    result = await db.execute(
        select(Farm).where(Farm.id == farm_id, Farm.user_id == user_id, Farm.active == True)
    )
    farm = result.scalar_one_or_none()
    if farm is None:
        raise HTTPException(status_code=404, detail="Farm not found.")
    return farm


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=FarmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new farm with a Leaflet-drawn polygon",
)
async def create_farm(
    body:         FarmCreateRequest,
    current_user: UserTokenData    = Depends(get_current_user),
    db:           AsyncSession     = Depends(get_db),
) -> FarmResponse:
    """
    Registers a farm from a GeoJSON polygon.

    Steps:
    1. Parse GeoJSON → PostGIS geometry via ST_GeomFromGeoJSON.
    2. Compute centroid (ST_Centroid → ST_X/ST_Y) server-side.
    3. Compute area_ha (ST_Area in geography projection → / 10000).
    4. Auto-detect nearest district from centroid coordinates.
    5. Insert farm row.
    """
    geojson_str = json.dumps(body.boundary_geojson)

    # Use PostGIS functions inside the INSERT to compute derived columns
    # We do this in two steps: insert with geom, then read back computed values.
    farm = Farm(
        user_id  = current_user.id,
        name     = body.name,
        crop     = body.crop,
    )
    db.add(farm)
    await db.flush()  # get farm.id

    # Update geometry and compute derived columns in one PostGIS statement
    await db.execute(
        text("""
            UPDATE farms SET
                boundary     = ST_GeomFromGeoJSON(:geojson),
                centroid_lat = ST_Y(ST_Centroid(ST_GeomFromGeoJSON(:geojson))),
                centroid_lon = ST_X(ST_Centroid(ST_GeomFromGeoJSON(:geojson))),
                area_ha      = ST_Area(ST_GeomFromGeoJSON(:geojson)::geography) / 10000.0
            WHERE id = :farm_id
        """),
        {"geojson": geojson_str, "farm_id": str(farm.id)},
    )
    await db.commit()
    await db.refresh(farm)

    # Detect district from computed centroid
    if farm.centroid_lat and farm.centroid_lon:
        farm.district = detect_district(farm.centroid_lat, farm.centroid_lon)
        await db.commit()
        await db.refresh(farm)

    # Read back boundary as GeoJSON for response
    result = await db.execute(
        text("SELECT ST_AsGeoJSON(boundary) FROM farms WHERE id = :id"),
        {"id": str(farm.id)},
    )
    boundary_json = result.scalar_one_or_none()

    return _farm_to_response(farm, boundary_json)


@router.get(
    "",
    response_model=FarmListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all active farms for the current user",
)
async def list_farms(
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> FarmListResponse:
    result = await db.execute(
        select(Farm)
        .where(Farm.user_id == current_user.id, Farm.active == True)
        .order_by(Farm.created_at.desc())
    )
    farms = result.scalars().all()

    # Batch-fetch boundary GeoJSON for all farms
    if farms:
        ids = [str(f.id) for f in farms]
        placeholders = ", ".join(f"'{fid}'" for fid in ids)
        geo_result = await db.execute(
            text(f"SELECT id::text, ST_AsGeoJSON(boundary) FROM farms WHERE id IN ({placeholders})")
        )
        geo_map = {row[0]: row[1] for row in geo_result}
    else:
        geo_map = {}

    farm_responses = [
        _farm_to_response(f, geo_map.get(str(f.id)))
        for f in farms
    ]
    return FarmListResponse(farms=farm_responses, total=len(farm_responses))


@router.get(
    "/{farm_id}",
    response_model=FarmResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single farm by ID",
)
async def get_farm(
    farm_id:      UUID,
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> FarmResponse:
    farm = await _get_farm_or_404(farm_id, current_user.id, db)
    result = await db.execute(
        text("SELECT ST_AsGeoJSON(boundary) FROM farms WHERE id = :id"),
        {"id": str(farm.id)},
    )
    boundary_json = result.scalar_one_or_none()
    return _farm_to_response(farm, boundary_json)


@router.patch(
    "/{farm_id}",
    response_model=FarmResponse,
    status_code=status.HTTP_200_OK,
    summary="Update farm name or crop type",
)
async def update_farm(
    farm_id:      UUID,
    name:         Optional[str] = None,
    crop:         Optional[str] = None,
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> FarmResponse:
    """Update mutable fields. Boundary cannot be changed — delete and re-register."""
    farm = await _get_farm_or_404(farm_id, current_user.id, db)
    if name:
        farm.name = name
    if crop and crop in ("Wheat", "Rice"):
        farm.crop = crop
    await db.commit()
    await db.refresh(farm)
    result = await db.execute(
        text("SELECT ST_AsGeoJSON(boundary) FROM farms WHERE id = :id"),
        {"id": str(farm.id)},
    )
    return _farm_to_response(farm, result.scalar_one_or_none())


@router.delete(
    "/{farm_id}",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete a farm (sets active=False, preserves all history)",
)
async def delete_farm(
    farm_id:      UUID,
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> dict:
    """
    Soft delete — sets active=False.
    Farm history (predictions, savings) is preserved for the season report.
    """
    farm = await _get_farm_or_404(farm_id, current_user.id, db)
    farm.active = False
    await db.commit()
    return {"deleted": True, "farm_id": str(farm_id)}