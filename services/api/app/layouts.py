from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .assets import AssetCatalog, RoomType
from .styles import StylePack, StylePlacement


LAYOUT_PIPELINE_VERSION = "multiroom-asset-layout-v2"
Point2D = tuple[float, float]


class LayoutStyleReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int = Field(ge=1)


class LayoutRoom(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    name: str
    room_type: RoomType = Field(alias="roomType")
    source: Literal["zone", "slab"]
    level_id: str | None = Field(alias="levelId")
    polygon: list[Point2D]
    area: float = Field(gt=0)
    centroid: Point2D


class LayoutPlacement(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    item_id: str = Field(alias="itemId")
    room_id: str = Field(alias="roomId")
    asset_id: str = Field(alias="assetId")
    kind: Literal["box", "cylinder", "sphere"]
    role: str
    collision_mode: Literal["solid", "surface"] = Field(alias="collisionMode")
    position: tuple[float, float, float]
    size: tuple[float, float, float]
    rotation_y_degrees: float = Field(alias="rotationYDegrees")


class LayoutManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["2.0"] = Field(alias="schemaVersion")
    layout_id: str = Field(alias="layoutId", pattern=r"^[0-9a-f]{64}$")
    pipeline_version: Literal["multiroom-asset-layout-v2"] = Field(alias="pipelineVersion")
    project_id: str = Field(alias="projectId")
    scene_revision: int = Field(alias="sceneRevision", ge=1)
    style: LayoutStyleReference
    asset_catalog: LayoutStyleReference = Field(alias="assetCatalog")
    status: Literal["ready", "partial", "fallback"]
    fallback_reason: Literal["no-room-polygon", "no-supported-room", "no-room-fits"] | None = Field(
        alias="fallbackReason",
        default=None,
    )
    selected_room_id: str | None = Field(alias="selectedRoomId", default=None)
    furnished_room_ids: list[str] = Field(alias="furnishedRoomIds")
    unfurnished_room_ids: list[str] = Field(alias="unfurnishedRoomIds")
    referenced_asset_bytes: int = Field(alias="referencedAssetBytes", ge=0)
    mobile_asset_budget_bytes: int = Field(alias="mobileAssetBudgetBytes", gt=0)
    mobile_asset_budget_exceeded: bool = Field(alias="mobileAssetBudgetExceeded")
    wall_clearance: float = Field(alias="wallClearance", ge=0)
    item_clearance: float = Field(alias="itemClearance", ge=0)
    rooms: list[LayoutRoom]
    placements: list[LayoutPlacement]


def _polygon_area(polygon: list[Point2D]) -> float:
    return abs(
        sum(
            start[0] * polygon[(index + 1) % len(polygon)][1]
            - polygon[(index + 1) % len(polygon)][0] * start[1]
            for index, start in enumerate(polygon)
        )
    ) / 2


def _polygon_centroid(polygon: list[Point2D]) -> Point2D:
    signed_twice_area = sum(
        start[0] * polygon[(index + 1) % len(polygon)][1]
        - polygon[(index + 1) % len(polygon)][0] * start[1]
        for index, start in enumerate(polygon)
    )
    if abs(signed_twice_area) < 1e-9:
        return (
            sum(point[0] for point in polygon) / len(polygon),
            sum(point[1] for point in polygon) / len(polygon),
        )
    factor = 1 / (3 * signed_twice_area)
    return (
        sum(
            (start[0] + polygon[(index + 1) % len(polygon)][0])
            * (
                start[0] * polygon[(index + 1) % len(polygon)][1]
                - polygon[(index + 1) % len(polygon)][0] * start[1]
            )
            for index, start in enumerate(polygon)
        )
        * factor,
        sum(
            (start[1] + polygon[(index + 1) % len(polygon)][1])
            * (
                start[0] * polygon[(index + 1) % len(polygon)][1]
                - polygon[(index + 1) % len(polygon)][0] * start[1]
            )
            for index, start in enumerate(polygon)
        )
        * factor,
    )


def _parse_polygon(value: Any) -> list[Point2D] | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    polygon: list[Point2D] = []
    for point in value:
        if (
            not isinstance(point, list)
            or len(point) != 2
            or any(isinstance(entry, bool) or not isinstance(entry, (int, float)) for entry in point)
        ):
            return None
        parsed = (float(point[0]), float(point[1]))
        if not all(math.isfinite(entry) for entry in parsed):
            return None
        polygon.append(parsed)
    if len(set(polygon)) < 3 or _polygon_area(polygon) < 4:
        return None
    return polygon


def _classify_room(node: dict[str, Any], name: str) -> RoomType:
    explicit = node.get("roomType")
    if explicit in {"living", "dining", "bedroom", "other"}:
        return explicit
    normalized = "".join(name.lower().split())
    if any(keyword in normalized for keyword in ("客餐", "livingdining")):
        return "living"
    if any(keyword in normalized for keyword in ("卧室", "主卧", "次卧", "bedroom")):
        return "bedroom"
    if any(keyword in normalized for keyword in ("餐厅", "餐区", "dining")):
        return "dining"
    if any(keyword in normalized for keyword in ("客厅", "起居", "living", "lounge")):
        return "living"
    return "other"


def extract_rooms(nodes: dict[str, dict[str, Any]]) -> list[LayoutRoom]:
    candidates: list[LayoutRoom] = []
    for source in ("zone", "slab"):
        for node_id, node in sorted(nodes.items()):
            if node.get("type") != source:
                continue
            polygon = _parse_polygon(node.get("polygon"))
            if polygon is None:
                continue
            name = node.get("name") if isinstance(node.get("name"), str) else node_id
            candidates.append(
                LayoutRoom(
                    id=node_id,
                    name=name,
                    roomType=_classify_room(node, name),
                    source=source,
                    levelId=node.get("parentId") if isinstance(node.get("parentId"), str) else None,
                    polygon=polygon,
                    area=round(_polygon_area(polygon), 6),
                    centroid=_polygon_centroid(polygon),
                )
            )
        if candidates:
            break
    return sorted(candidates, key=lambda room: (-room.area, room.id))


def _rotated_corners(placement: StylePlacement) -> list[Point2D]:
    width, _, depth = placement.size
    angle = math.radians(placement.rotation_y_degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    center_x, _, center_z = placement.position
    return [
        (
            center_x + local_x * cosine + local_z * sine,
            center_z - local_x * sine + local_z * cosine,
        )
        for local_x, local_z in (
            (-width / 2, -depth / 2),
            (width / 2, -depth / 2),
            (width / 2, depth / 2),
            (-width / 2, depth / 2),
        )
    ]


def _item_bounds(
    placements: list[StylePlacement],
) -> dict[str, tuple[float, float, float, float]]:
    points: dict[str, list[Point2D]] = defaultdict(list)
    for placement in placements:
        if placement.collision_mode == "solid":
            points[placement.item_id].extend(_rotated_corners(placement))
    return {
        item_id: (
            min(point[0] for point in corners),
            min(point[1] for point in corners),
            max(point[0] for point in corners),
            max(point[1] for point in corners),
        )
        for item_id, corners in points.items()
    }


def _point_in_polygon(point: Point2D, polygon: list[Point2D]) -> bool:
    inside = False
    x, z = point
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if _point_segment_distance(point, start, end) < 1e-8:
            return True
        if (start[1] > z) != (end[1] > z):
            intersection_x = (
                (end[0] - start[0]) * (z - start[1]) / (end[1] - start[1])
                + start[0]
            )
            if x < intersection_x:
                inside = not inside
    return inside


def _point_segment_distance(point: Point2D, start: Point2D, end: Point2D) -> float:
    dx = end[0] - start[0]
    dz = end[1] - start[1]
    length_squared = dx * dx + dz * dz
    if length_squared == 0:
        return math.dist(point, start)
    ratio = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dz)
            / length_squared,
        ),
    )
    projection = (start[0] + ratio * dx, start[1] + ratio * dz)
    return math.dist(point, projection)


def _orientation(start: Point2D, end: Point2D, point: Point2D) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (
        end[1] - start[1]
    ) * (point[0] - start[0])


def _segments_intersect(
    first_start: Point2D,
    first_end: Point2D,
    second_start: Point2D,
    second_end: Point2D,
) -> bool:
    epsilon = 1e-9
    orientations = (
        _orientation(first_start, first_end, second_start),
        _orientation(first_start, first_end, second_end),
        _orientation(second_start, second_end, first_start),
        _orientation(second_start, second_end, first_end),
    )
    first_start_side, first_end_side, second_start_side, second_end_side = orientations
    if (
        first_start_side * first_end_side < -epsilon
        and second_start_side * second_end_side < -epsilon
    ):
        return True

    def lies_on_segment(point: Point2D, start: Point2D, end: Point2D) -> bool:
        return (
            min(start[0], end[0]) - epsilon
            <= point[0]
            <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon
            <= point[1]
            <= max(start[1], end[1]) + epsilon
        )

    return (
        abs(first_start_side) <= epsilon
        and lies_on_segment(second_start, first_start, first_end)
        or abs(first_end_side) <= epsilon
        and lies_on_segment(second_end, first_start, first_end)
        or abs(second_start_side) <= epsilon
        and lies_on_segment(first_start, second_start, second_end)
        or abs(second_end_side) <= epsilon
        and lies_on_segment(first_end, second_start, second_end)
    )


def _segment_distance(
    first_start: Point2D,
    first_end: Point2D,
    second_start: Point2D,
    second_end: Point2D,
) -> float:
    if _segments_intersect(first_start, first_end, second_start, second_end):
        return 0
    return min(
        _point_segment_distance(first_start, second_start, second_end),
        _point_segment_distance(first_end, second_start, second_end),
        _point_segment_distance(second_start, first_start, first_end),
        _point_segment_distance(second_end, first_start, first_end),
    )


def _bounds_fit_room(
    bounds: tuple[float, float, float, float],
    translation: Point2D,
    room: LayoutRoom,
    clearance: float,
) -> bool:
    minimum_x, minimum_z, maximum_x, maximum_z = bounds
    corners = [
        (minimum_x + translation[0], minimum_z + translation[1]),
        (maximum_x + translation[0], minimum_z + translation[1]),
        (maximum_x + translation[0], maximum_z + translation[1]),
        (minimum_x + translation[0], maximum_z + translation[1]),
    ]
    item_edges = [
        (start, corners[(index + 1) % len(corners)])
        for index, start in enumerate(corners)
    ]
    room_edges = [
        (start, room.polygon[(index + 1) % len(room.polygon)])
        for index, start in enumerate(room.polygon)
    ]
    return all(_point_in_polygon(point, room.polygon) for point in corners) and all(
        _segment_distance(item_start, item_end, room_start, room_end)
        >= clearance - 1e-8
        for item_start, item_end in item_edges
        for room_start, room_end in room_edges
    )


def _items_have_clearance(
    bounds: dict[str, tuple[float, float, float, float]],
    clearance: float,
) -> bool:
    items = sorted(bounds.items())
    for index, (_, first) in enumerate(items):
        for _, second in items[index + 1 :]:
            separated = (
                first[2] + clearance <= second[0]
                or second[2] + clearance <= first[0]
                or first[3] + clearance <= second[1]
                or second[3] + clearance <= first[1]
            )
            if not separated:
                return False
    return True


def _identity_payload(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def generate_layout(
    project_id: str,
    scene_revision: int,
    nodes: dict[str, dict[str, Any]],
    style: StylePack,
    asset_catalog: AssetCatalog,
) -> LayoutManifest:
    rooms = extract_rooms(nodes)
    base = {
        "schemaVersion": "2.0",
        "pipelineVersion": LAYOUT_PIPELINE_VERSION,
        "projectId": project_id,
        "sceneRevision": scene_revision,
        "style": {"id": style.id, "version": style.version},
        "assetCatalog": {
            "id": asset_catalog.manifest.id,
            "version": asset_catalog.manifest.version,
        },
        "wallClearance": style.layout.wall_clearance,
        "itemClearance": style.layout.item_clearance,
        "rooms": [room.model_dump(by_alias=True, mode="json") for room in rooms],
    }
    if not rooms:
        payload = {
            **base,
            "status": "fallback",
            "fallbackReason": "no-room-polygon",
            "selectedRoomId": None,
            "furnishedRoomIds": [],
            "unfurnishedRoomIds": [],
            "referencedAssetBytes": 0,
            "mobileAssetBudgetBytes": asset_catalog.manifest.mobile_budget_bytes,
            "mobileAssetBudgetExceeded": False,
            "placements": [],
        }
        return LayoutManifest(layoutId=_identity_payload(payload), **payload)

    placements: list[LayoutPlacement] = []
    furnished_room_ids: list[str] = []
    unfurnished_room_ids: list[str] = []
    for room in rooms:
        recipe = asset_catalog.recipe(room.room_type)
        if not recipe:
            unfurnished_room_ids.append(room.id)
            continue
        template = [
            StylePlacement(
                id=entry.id,
                itemId=entry.item_id,
                assetId=entry.asset_id,
                kind=asset_catalog.assets[entry.asset_id].fallback.kind,
                role=entry.role,
                collisionMode=entry.collision_mode,
                position=entry.position,
                size=asset_catalog.assets[entry.asset_id].canonical_size,
                rotationYDegrees=entry.rotation_y_degrees,
            )
            for entry in recipe
        ]
        missing_roles = sorted({entry.role for entry in template if entry.role not in style.materials})
        if missing_roles:
            raise ValueError(f"style {style.id} lacks catalog material roles: {missing_roles}")
        bounds = _item_bounds(template)
        if not _items_have_clearance(bounds, style.layout.item_clearance):
            raise ValueError(f"{room.room_type} asset recipe violates item clearance")
        all_points = [
            point
            for placement in template
            if placement.collision_mode == "solid"
            for point in _rotated_corners(placement)
        ]
        template_center = (
            (min(point[0] for point in all_points) + max(point[0] for point in all_points)) / 2,
            (min(point[1] for point in all_points) + max(point[1] for point in all_points)) / 2,
        )
        translation = (
            room.centroid[0] - template_center[0],
            room.centroid[1] - template_center[1],
        )
        if not all(
            _bounds_fit_room(item_bounds, translation, room, style.layout.wall_clearance)
            for item_bounds in bounds.values()
        ):
            unfurnished_room_ids.append(room.id)
            continue
        placements.extend(
            LayoutPlacement(
                id=f"{room.id}-{placement.id}",
                itemId=placement.item_id,
                roomId=room.id,
                assetId=placement.asset_id,
                kind=placement.kind,
                role=placement.role,
                collisionMode=placement.collision_mode,
                position=(
                    placement.position[0] + translation[0],
                    placement.position[1],
                    placement.position[2] + translation[1],
                ),
                size=placement.size,
                rotationYDegrees=placement.rotation_y_degrees,
            )
            for placement in template
        )
        furnished_room_ids.append(room.id)

    referenced_asset_ids = {
        placement.asset_id
        for placement in placements
        if asset_catalog.assets[placement.asset_id].delivery is not None
    }
    referenced_asset_bytes = sum(
        asset_catalog.assets[asset_id].delivery.bytes  # type: ignore[union-attr]
        for asset_id in referenced_asset_ids
    )
    supported_rooms = [room for room in rooms if room.room_type != "other"]
    if furnished_room_ids:
        status = "ready" if len(furnished_room_ids) == len(rooms) else "partial"
        fallback_reason = None
    else:
        status = "fallback"
        fallback_reason = "no-room-fits" if supported_rooms else "no-supported-room"
    payload = {
        **base,
        "status": status,
        "fallbackReason": fallback_reason,
        "selectedRoomId": furnished_room_ids[0] if furnished_room_ids else None,
        "furnishedRoomIds": furnished_room_ids,
        "unfurnishedRoomIds": unfurnished_room_ids,
        "referencedAssetBytes": referenced_asset_bytes,
        "mobileAssetBudgetBytes": asset_catalog.manifest.mobile_budget_bytes,
        "mobileAssetBudgetExceeded": (
            referenced_asset_bytes > asset_catalog.manifest.mobile_budget_bytes
        ),
        "placements": [
            placement.model_dump(by_alias=True, mode="json")
            for placement in placements
        ],
    }
    return LayoutManifest(layoutId=_identity_payload(payload), **payload)
