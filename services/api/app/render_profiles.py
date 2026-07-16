from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PROFILE_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"
VIEW_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"


class RenderResourceDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(pattern=r"^(?:environment|materials)/[A-Za-z0-9_./-]+\.(?:hdr|jpg)$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0, le=20 * 1024 * 1024)


class RenderResource(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    kind: Literal["environment", "color", "normal", "roughness"]
    author: str = Field(min_length=1)
    source_page_url: str = Field(alias="sourcePageUrl", pattern=r"^https://polyhaven\.com/a/")
    download_url: str = Field(alias="downloadUrl", pattern=r"^https://dl\.polyhaven\.org/file/")
    delivery: RenderResourceDelivery


class RenderLicense(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    spdx: Literal["CC0-1.0"]
    url: str
    local_notice: str = Field(alias="localNotice")


class MaterialSet(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    diffuse: str
    normal: str
    roughness: str
    tile_size_meters: float = Field(alias="tileSizeMeters", gt=0, le=10)
    normal_strength: float = Field(alias="normalStrength", ge=0, le=2)


class RenderEnvironment(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resource_id: str = Field(alias="resourceId")
    strength: float = Field(gt=0, le=5)
    rotation_degrees: float = Field(alias="rotationDegrees", ge=-360, le=360)


class RenderView(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(pattern=VIEW_ID_PATTERN)
    name: str = Field(min_length=1, max_length=40)
    kind: Literal["overview", "room"]
    room_type: Literal["living", "dining", "bedroom"] | None = Field(alias="roomType")
    lens_millimeters: float = Field(alias="lensMillimeters", ge=18, le=85)
    azimuth_degrees: float = Field(alias="azimuthDegrees", ge=-360, le=360)

    @model_validator(mode="after")
    def validate_room_view(self) -> "RenderView":
        if (self.kind == "room") != (self.room_type is not None):
            raise ValueError("room views require roomType and overview views cannot declare it")
        return self


class RenderProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    version: int = Field(ge=1)
    engine: Literal["BLENDER_EEVEE", "CYCLES"]
    device_preference: Literal["RASTER", "METAL_PREFERRED"] = Field(alias="devicePreference")
    width: int = Field(ge=320, le=4096)
    height: int = Field(ge=240, le=4096)
    samples: int = Field(ge=1, le=1024)
    noise_threshold: float | None = Field(alias="noiseThreshold", default=None, gt=0, le=1)
    denoise: bool
    exposure: float = Field(ge=-5, le=5)
    environment: RenderEnvironment | None
    floor_material_set: str | None = Field(alias="floorMaterialSet")
    views: list[RenderView] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_engine(self) -> "RenderProfile":
        if self.engine == "BLENDER_EEVEE":
            if self.device_preference != "RASTER" or self.noise_threshold is not None or self.denoise:
                raise ValueError("EEVEE profile cannot request Cycles-only settings")
        elif self.noise_threshold is None or not self.denoise:
            raise ValueError("Cycles profile requires adaptive sampling and denoising")
        if len({view.id for view in self.views}) != len(self.views):
            raise ValueError("render profile view ids must be unique")
        return self


class RenderProfileManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    version: int = Field(ge=1)
    license: RenderLicense
    resources: list[RenderResource]
    material_sets: dict[str, MaterialSet] = Field(alias="materialSets")
    profiles: dict[str, RenderProfile]

    @model_validator(mode="after")
    def validate_references(self) -> "RenderProfileManifest":
        resources = {resource.id: resource for resource in self.resources}
        if len(resources) != len(self.resources):
            raise ValueError("render resource ids must be unique")
        for material_id, material in self.material_sets.items():
            expected = {
                material.diffuse: "color",
                material.normal: "normal",
                material.roughness: "roughness",
            }
            for resource_id, kind in expected.items():
                resource = resources.get(resource_id)
                if resource is None or resource.kind != kind:
                    raise ValueError(f"material set {material_id} has an invalid {kind} resource")
        for profile_id, profile in self.profiles.items():
            if re.fullmatch(PROFILE_ID_PATTERN, profile_id) is None:
                raise ValueError("render profile id is invalid")
            if profile.environment:
                resource = resources.get(profile.environment.resource_id)
                if resource is None or resource.kind != "environment":
                    raise ValueError(f"profile {profile_id} has an invalid environment")
            if profile.floor_material_set and profile.floor_material_set not in self.material_sets:
                raise ValueError(f"profile {profile_id} has an invalid floor material set")
        return self


class RenderProfileCatalog:
    def __init__(self, manifest_path: Path | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        self.manifest_path = manifest_path or repository_root / "packages" / "render-assets" / "catalog.json"
        self.directory = self.manifest_path.parent
        self.manifest = RenderProfileManifest.model_validate_json(
            self.manifest_path.read_text(encoding="utf-8")
        )
        self.resources = {resource.id: resource for resource in self.manifest.resources}
        self._validate_files()

    def _validate_files(self) -> None:
        notice_path = (self.directory / self.manifest.license.local_notice).resolve()
        if not notice_path.is_relative_to(self.directory.resolve()) or not notice_path.is_file():
            raise ValueError("render resource license notice is missing")
        for resource in self.manifest.resources:
            path = (self.directory / resource.delivery.path).resolve()
            if not path.is_relative_to(self.directory.resolve()) or not path.is_file():
                raise ValueError(f"render resource is missing: {resource.id}")
            content = path.read_bytes()
            if len(content) != resource.delivery.bytes:
                raise ValueError(f"render resource byte count changed: {resource.id}")
            if hashlib.sha256(content).hexdigest() != resource.delivery.sha256:
                raise ValueError(f"render resource hash changed: {resource.id}")

    def get(self, profile_id: str) -> RenderProfile | None:
        return self.manifest.profiles.get(profile_id)
