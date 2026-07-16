from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RoomType = Literal["living", "dining", "bedroom", "other"]
PrimitiveKind = Literal["box", "cylinder", "sphere"]


class CatalogLicense(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    spdx: Literal["CC0-1.0"]
    url: str
    local_notice: str = Field(alias="localNotice")


class SourcePackage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    site_version: str = Field(alias="siteVersion")
    embedded_version: str = Field(alias="embeddedVersion")
    author: str
    source_url: str = Field(alias="sourceUrl")
    download_url: str = Field(alias="downloadUrl")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license: CatalogLicense


class AssetDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(pattern=r"^/catalog-assets/models/[a-z0-9-]+\.glb$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0, le=2 * 1024 * 1024)


class AssetFallback(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    kind: PrimitiveKind
    material_role: str = Field(alias="materialRole", pattern=r"^[a-z][a-z0-9-]{0,31}$")


class CatalogAsset(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    kind: Literal["model", "procedural"]
    room_types: list[RoomType] = Field(alias="roomTypes", min_length=1)
    source_entry: str | None = Field(alias="sourceEntry", default=None)
    source_sha256: str | None = Field(alias="sourceSha256", default=None)
    source_material_sha256: str | None = Field(alias="sourceMaterialSha256", default=None)
    canonical_size: tuple[float, float, float] = Field(alias="canonicalSize")
    delivery: AssetDelivery | None = None
    fallback: AssetFallback

    @model_validator(mode="after")
    def validate_kind(self) -> "CatalogAsset":
        if any(value <= 0 for value in self.canonical_size):
            raise ValueError("asset canonical size values must be positive")
        source_values = (
            self.source_entry,
            self.source_sha256,
            self.source_material_sha256,
            self.delivery,
        )
        if self.kind == "model" and any(value is None for value in source_values):
            raise ValueError("model assets require audited source and delivery metadata")
        if self.kind == "procedural" and any(value is not None for value in source_values):
            raise ValueError("procedural assets cannot declare external source or delivery")
        return self


class RoomRecipePlacement(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    item_id: str = Field(alias="itemId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    asset_id: str = Field(alias="assetId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    role: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    collision_mode: Literal["solid", "surface"] = Field(alias="collisionMode")
    position: tuple[float, float, float]
    rotation_y_degrees: float = Field(alias="rotationYDegrees", ge=-360, le=360)


class AssetCatalogManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    version: int = Field(ge=1)
    mobile_budget_bytes: int = Field(alias="mobileBudgetBytes", gt=0)
    source_package: SourcePackage = Field(alias="sourcePackage")
    assets: list[CatalogAsset] = Field(min_length=1)
    room_recipes: dict[Literal["living", "dining", "bedroom"], list[RoomRecipePlacement]] = Field(
        alias="roomRecipes"
    )

    @model_validator(mode="after")
    def validate_references(self) -> "AssetCatalogManifest":
        asset_ids = [asset.id for asset in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("catalog asset ids must be unique")
        assets = {asset.id: asset for asset in self.assets}
        for room_type in ("living", "dining", "bedroom"):
            recipe = self.room_recipes.get(room_type)
            if not recipe:
                raise ValueError(f"catalog requires a {room_type} recipe")
            placement_ids = [placement.id for placement in recipe]
            if len(placement_ids) != len(set(placement_ids)):
                raise ValueError(f"{room_type} recipe placement ids must be unique")
            for placement in recipe:
                asset = assets.get(placement.asset_id)
                if asset is None:
                    raise ValueError(f"recipe references missing asset: {placement.asset_id}")
                if room_type not in asset.room_types:
                    raise ValueError(f"asset {asset.id} is not allowed in {room_type}")
        return self


class AssetCatalog:
    def __init__(self, manifest_path: Path | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        self.manifest_path = manifest_path or repository_root / "packages" / "asset-catalog" / "catalog.json"
        self.directory = self.manifest_path.parent
        self.manifest = AssetCatalogManifest.model_validate_json(
            self.manifest_path.read_text(encoding="utf-8")
        )
        self.assets = {asset.id: asset for asset in self.manifest.assets}
        self._validate_files()

    @property
    def models_directory(self) -> Path:
        return self.directory / "models"

    def _validate_files(self) -> None:
        for asset in self.manifest.assets:
            if asset.delivery is None:
                continue
            path = self.models_directory / asset.delivery.url.rsplit("/", maxsplit=1)[-1]
            if not path.is_file():
                raise ValueError(f"catalog model is missing: {asset.id}")
            content = path.read_bytes()
            if len(content) != asset.delivery.bytes:
                raise ValueError(f"catalog model byte count changed: {asset.id}")
            if hashlib.sha256(content).hexdigest() != asset.delivery.sha256:
                raise ValueError(f"catalog model hash changed: {asset.id}")

    def recipe(self, room_type: RoomType) -> list[RoomRecipePlacement]:
        if room_type == "other":
            return []
        return self.manifest.room_recipes[room_type]
