from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


STYLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class LicenseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spdx: Literal["LicenseRef-Project-Authored"]
    source: Literal["project-authored"]


class PbrMaterial(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    base_color: str = Field(alias="baseColor", pattern=HEX_COLOR_PATTERN)
    metallic: float = Field(ge=0, le=1)
    roughness: float = Field(ge=0, le=1)


class StyleEnvironment(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    background_color: str = Field(alias="backgroundColor", pattern=HEX_COLOR_PATTERN)
    ambient_color: str = Field(alias="ambientColor", pattern=HEX_COLOR_PATTERN)
    ambient_intensity: float = Field(alias="ambientIntensity", ge=0, le=20)
    sun_color: str = Field(alias="sunColor", pattern=HEX_COLOR_PATTERN)
    sun_intensity: float = Field(alias="sunIntensity", ge=0, le=20)
    sun_direction: tuple[float, float, float] = Field(alias="sunDirection")


class StyleCamera(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    alpha_degrees: float = Field(alias="alphaDegrees", ge=-360, le=360)
    beta_degrees: float = Field(alias="betaDegrees", gt=0, lt=90)
    radius_multiplier: float = Field(alias="radiusMultiplier", ge=0.5, le=4)


class RenderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=320, le=4096)
    height: int = Field(ge=240, le=4096)
    samples: int = Field(ge=1, le=1024)


class StyleAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    kind: Literal["procedural"]
    source: Literal["project-authored"]
    license: LicenseMetadata


class StylePlacement(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    asset_id: str = Field(alias="assetId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    kind: Literal["box", "cylinder", "sphere"]
    role: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    position: tuple[float, float, float]
    size: tuple[float, float, float]
    rotation_y_degrees: float = Field(alias="rotationYDegrees", ge=-360, le=360)

    @model_validator(mode="after")
    def validate_size(self) -> "StylePlacement":
        if any(value <= 0 for value in self.size):
            raise ValueError("placement size values must be positive")
        return self


class StyleLayout(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    floor_padding: float = Field(alias="floorPadding", ge=0, le=20)
    placements: list[StylePlacement]


class StylePack(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    license: LicenseMetadata
    materials: dict[str, PbrMaterial]
    environment: StyleEnvironment
    camera: StyleCamera
    output: RenderOutput
    assets: list[StyleAsset]
    layout: StyleLayout

    @model_validator(mode="after")
    def validate_references(self) -> "StylePack":
        if not {"architecture", "floor"}.issubset(self.materials):
            raise ValueError("style materials must define architecture and floor roles")
        if any(not ROLE_RE.fullmatch(role) for role in self.materials):
            raise ValueError("style material role is invalid")
        asset_ids = [asset.id for asset in self.assets]
        placement_ids = [placement.id for placement in self.layout.placements]
        if len(asset_ids) != len(set(asset_ids)) or len(placement_ids) != len(set(placement_ids)):
            raise ValueError("style asset and placement ids must be unique")
        missing_assets = [
            placement.asset_id
            for placement in self.layout.placements
            if placement.asset_id not in asset_ids
        ]
        missing_roles = [
            placement.role
            for placement in self.layout.placements
            if placement.role not in self.materials
        ]
        if missing_assets:
            raise ValueError(f"placements reference missing assets: {missing_assets}")
        if missing_roles:
            raise ValueError(f"placements reference missing material roles: {missing_roles}")
        return self


class StyleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    name: str
    description: str


class StyleCatalog:
    def __init__(self, directory: Path | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        self.directory = directory or repository_root / "packages" / "style-schema" / "styles"
        self._styles: dict[str, tuple[StylePack, Path]] = {}
        for path in sorted(self.directory.glob("*.json")):
            style = StylePack.model_validate_json(path.read_text(encoding="utf-8"))
            if style.id in self._styles:
                raise ValueError(f"duplicate style id: {style.id}")
            self._styles[style.id] = (style, path)
        if not self._styles:
            raise ValueError("style catalog is empty")

    def list(self) -> list[StyleSummary]:
        return [
            StyleSummary(
                id=style.id,
                version=style.version,
                name=style.name,
                description=style.description,
            )
            for style, _ in sorted(self._styles.values(), key=lambda item: item[0].id)
        ]

    def get(self, style_id: str) -> StylePack | None:
        if not STYLE_ID_RE.fullmatch(style_id):
            return None
        entry = self._styles.get(style_id)
        return entry[0] if entry else None

    def path_for(self, style_id: str) -> Path:
        entry = self._styles.get(style_id)
        if entry is None:
            raise KeyError(style_id)
        return entry[1]
