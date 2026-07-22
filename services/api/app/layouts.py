from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .assets import AssetCatalog, RoomType
from .styles import StylePack, StylePlacement


LAYOUT_PIPELINE_VERSION = "multiroom-opening-clearance-layout-v5"
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


class LayoutOpening(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    source_type: Literal["door", "window"] = Field(alias="sourceType")
    opening_kind: Literal["door", "window", "opening"] = Field(alias="openingKind")
    operation_type: str = Field(alias="operationType")
    wall_id: str = Field(alias="wallId")
    level_id: str | None = Field(alias="levelId")
    room_ids: list[str] = Field(alias="roomIds")
    center: Point2D
    tangent: Point2D
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    sill_height: float = Field(alias="sillHeight", ge=0)
    clearance_type: Literal["swing", "approach"] = Field(alias="clearanceType")
    clearance_depth: float = Field(alias="clearanceDepth", gt=0)
    clearance_polygon: list[Point2D] = Field(alias="clearancePolygon", min_length=3)


class LayoutManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["3.0"] = Field(alias="schemaVersion")
    layout_id: str = Field(alias="layoutId", pattern=r"^[0-9a-f]{64}$")
    pipeline_version: Literal["multiroom-opening-clearance-layout-v5"] = Field(
        alias="pipelineVersion"
    )
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
    placement_search: Literal["bounded-grid-v1"] = Field(alias="placementSearch")
    opening_clearance_validated: bool = Field(alias="openingClearanceValidated")
    ignored_opening_ids: list[str] = Field(alias="ignoredOpeningIds")
    opening_blocked_room_ids: list[str] = Field(alias="openingBlockedRoomIds")
    rooms: list[LayoutRoom]
    openings: list[LayoutOpening]
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


def _parse_polygon(value: Any, minimum_area: float = 4) -> list[Point2D] | None:
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
    if len(set(polygon)) < 3 or _polygon_area(polygon) < minimum_area:
        return None
    return polygon


def _classify_room(node: dict[str, Any], name: str) -> RoomType:
    explicit = node.get("roomType")
    if explicit in {"living", "dining", "bedroom", "kitchen", "bathroom", "other"}:
        return explicit
    normalized = "".join(name.lower().split())
    if any(keyword in normalized for keyword in ("客餐", "livingdining")):
        return "living"
    if any(keyword in normalized for keyword in ("卧室", "主卧", "次卧", "bedroom")):
        return "bedroom"
    if any(keyword in normalized for keyword in ("厨房", "厨区", "kitchen")):
        return "kitchen"
    if any(keyword in normalized for keyword in ("卫生间", "浴室", "洗手间", "bathroom")):
        return "bathroom"
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
            metadata = node.get("metadata")
            is_reviewed_truth = (
                isinstance(metadata, dict)
                and isinstance(metadata.get("reviewedGroundTruth"), dict)
            )
            polygon = _parse_polygon(
                node.get("polygon"),
                minimum_area=1 if is_reviewed_truth else 4,
            )
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


def _finite_vector(value: Any, length: int) -> tuple[float, ...] | None:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != length
        or any(isinstance(entry, bool) or not isinstance(entry, (int, float)) for entry in value)
    ):
        return None
    parsed = tuple(float(entry) for entry in value)
    return parsed if all(math.isfinite(entry) for entry in parsed) else None


def _oriented_rectangle(
    center: Point2D,
    tangent: Point2D,
    half_width: float,
    half_depth: float,
) -> list[Point2D]:
    normal = (-tangent[1], tangent[0])
    return [
        (
            center[0] + tangent[0] * along + normal[0] * across,
            center[1] + tangent[1] * along + normal[1] * across,
        )
        for along, across in (
            (-half_width, -half_depth),
            (half_width, -half_depth),
            (half_width, half_depth),
            (-half_width, half_depth),
        )
    ]


def _polygons_overlap(first: list[Point2D], second: list[Point2D]) -> bool:
    if any(_point_in_polygon(point, second) for point in first):
        return True
    if any(_point_in_polygon(point, first) for point in second):
        return True
    first_edges = [
        (point, first[(index + 1) % len(first)]) for index, point in enumerate(first)
    ]
    second_edges = [
        (point, second[(index + 1) % len(second)]) for index, point in enumerate(second)
    ]
    return any(
        _segments_intersect(first_start, first_end, second_start, second_end)
        for first_start, first_end in first_edges
        for second_start, second_end in second_edges
    )


def extract_openings(
    nodes: dict[str, dict[str, Any]],
    rooms: list[LayoutRoom],
) -> tuple[list[LayoutOpening], list[str]]:
    openings: list[LayoutOpening] = []
    ignored: list[str] = []
    for node_id, node in sorted(nodes.items()):
        source_type = node.get("type")
        if source_type not in {"door", "window"}:
            continue
        wall_id_value = node.get("wallId") or node.get("parentId")
        wall_id = wall_id_value if isinstance(wall_id_value, str) else None
        wall = nodes.get(wall_id) if wall_id else None
        wall_start = _finite_vector(wall.get("start"), 2) if isinstance(wall, dict) else None
        wall_end = _finite_vector(wall.get("end"), 2) if isinstance(wall, dict) else None
        position = _finite_vector(node.get("position", [0, 0, 0]), 3)
        plan_center = _finite_vector(node.get("planCenter"), 2)
        plan_tangent = _finite_vector(node.get("planTangent"), 2)
        metadata = node.get("metadata")
        has_reviewed_ground_truth = (
            isinstance(metadata, dict)
            and isinstance(metadata.get("reviewedGroundTruth"), dict)
            and metadata.get("worldPlanCenterSource") == "reviewed-ground-truth"
        )
        has_plan_override = (
            has_reviewed_ground_truth
            and plan_center is not None
            and plan_tangent is not None
        )
        if (
            wall_id is None
            or not isinstance(wall, dict)
            or wall.get("type") != "wall"
            or wall_start is None
            or wall_end is None
            or position is None
            or abs(float(wall.get("curveOffset", 0) or 0)) > 1e-9
        ):
            ignored.append(node_id)
            continue
        wall_dx = wall_end[0] - wall_start[0]
        wall_dz = wall_end[1] - wall_start[1]
        wall_length = math.hypot(wall_dx, wall_dz)
        width_default, height_default = ((0.9, 2.1) if source_type == "door" else (1.5, 1.5))
        width_value = node.get("width", width_default)
        height_value = node.get("height", height_default)
        plan_tangent_length = (
            math.hypot(plan_tangent[0], plan_tangent[1]) if plan_tangent is not None else 0.0
        )
        if (
            wall_length < 1e-9
            or isinstance(width_value, bool)
            or not isinstance(width_value, (int, float))
            or isinstance(height_value, bool)
            or not isinstance(height_value, (int, float))
            or (has_plan_override and plan_tangent_length < 1e-9)
        ):
            ignored.append(node_id)
            continue
        width = float(width_value)
        height = float(height_value)
        if (
            not math.isfinite(width)
            or not math.isfinite(height)
            or width <= 0
            or height <= 0
            or (not has_plan_override and (position[0] < 0 or position[0] > wall_length))
        ):
            ignored.append(node_id)
            continue
        if has_plan_override:
            assert plan_center is not None and plan_tangent is not None
            tangent = (
                plan_tangent[0] / plan_tangent_length,
                plan_tangent[1] / plan_tangent_length,
            )
            center = (plan_center[0], plan_center[1])
        else:
            tangent = (wall_dx / wall_length, wall_dz / wall_length)
            normal = (-tangent[1], tangent[0])
            center = (
                wall_start[0] + tangent[0] * position[0] + normal[0] * position[2],
                wall_start[1] + tangent[1] * position[0] + normal[1] * position[2],
            )
        if source_type == "door":
            opening_kind = node.get("openingKind", "door")
            opening_kind = opening_kind if opening_kind in {"door", "opening"} else "door"
            operation_type = node.get("doorType", "hinged")
            operation_type = operation_type if isinstance(operation_type, str) else "hinged"
            if opening_kind == "door" and operation_type in {"hinged", "double", "french", "folding"}:
                clearance_type: Literal["swing", "approach"] = "swing"
                clearance_depth = max(0.9, width)
            else:
                clearance_type = "approach"
                clearance_depth = 1.2 if operation_type.startswith("garage-") else 0.75
        else:
            opening_kind_value = node.get("openingKind", "window")
            opening_kind = opening_kind_value if opening_kind_value in {"window", "opening"} else "window"
            operation_type_value = node.get("windowType", "fixed")
            operation_type = operation_type_value if isinstance(operation_type_value, str) else "fixed"
            clearance_type = "approach"
            clearance_depth = 0.6
        clearance_polygon = _oriented_rectangle(
            center,
            tangent,
            width / 2 + 0.1,
            clearance_depth,
        )
        level_id = wall.get("parentId") if isinstance(wall.get("parentId"), str) else None
        room_ids = sorted(
            room.id
            for room in rooms
            if (level_id is None or room.level_id == level_id)
            and _polygons_overlap(clearance_polygon, room.polygon)
        )
        openings.append(
            LayoutOpening(
                id=node_id,
                sourceType=source_type,
                openingKind=opening_kind,
                operationType=operation_type,
                wallId=wall_id,
                levelId=level_id,
                roomIds=room_ids,
                center=center,
                tangent=tangent,
                width=width,
                height=height,
                sillHeight=max(0.0, position[1] - height / 2),
                clearanceType=clearance_type,
                clearanceDepth=clearance_depth,
                clearancePolygon=clearance_polygon,
            )
        )
    return openings, ignored


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


def _bounds_overlap_polygon(
    bounds: tuple[float, float, float, float],
    translation: Point2D,
    polygon: list[Point2D],
) -> bool:
    minimum_x, minimum_z, maximum_x, maximum_z = bounds
    corners = [
        (minimum_x + translation[0], minimum_z + translation[1]),
        (maximum_x + translation[0], minimum_z + translation[1]),
        (maximum_x + translation[0], maximum_z + translation[1]),
        (minimum_x + translation[0], maximum_z + translation[1]),
    ]
    return _polygons_overlap(corners, polygon)


def _offset_values(limit: float, step: float = 0.25) -> list[float]:
    values = [0.0]
    steps = int(limit // step)
    for index in range(1, steps + 1):
        values.extend((index * step, -index * step))
    if limit - steps * step > 1e-8:
        values.extend((limit, -limit))
    return values


def _candidate_translations(
    room: LayoutRoom,
    bounds: dict[str, tuple[float, float, float, float]],
    template_center: Point2D,
    wall_clearance: float,
) -> list[Point2D]:
    room_x = [point[0] for point in room.polygon]
    room_z = [point[1] for point in room.polygon]
    template_minimum_x = min(value[0] for value in bounds.values())
    template_minimum_z = min(value[1] for value in bounds.values())
    template_maximum_x = max(value[2] for value in bounds.values())
    template_maximum_z = max(value[3] for value in bounds.values())
    maximum_offset_x = max(
        0.0,
        (
            max(room_x)
            - min(room_x)
            - (template_maximum_x - template_minimum_x)
            - wall_clearance * 2
        )
        / 2,
    )
    maximum_offset_z = max(
        0.0,
        (
            max(room_z)
            - min(room_z)
            - (template_maximum_z - template_minimum_z)
            - wall_clearance * 2
        )
        / 2,
    )
    base = (
        room.centroid[0] - template_center[0],
        room.centroid[1] - template_center[1],
    )
    offsets = [
        (offset_x, offset_z)
        for offset_x in _offset_values(maximum_offset_x)
        for offset_z in _offset_values(maximum_offset_z)
    ]
    offsets.sort(
        key=lambda offset: (
            round(offset[0] * offset[0] + offset[1] * offset[1], 8),
            abs(offset[0]) + abs(offset[1]),
            offset[1],
            offset[0],
        )
    )
    return [(base[0] + offset[0], base[1] + offset[1]) for offset in offsets[:4096]]


def _identity_payload(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _template_variants(
    room: LayoutRoom,
    template: list[StylePlacement],
) -> list[list[StylePlacement]]:
    variants = [template]
    if room.room_type == "living":
        no_chair = [
            placement
            for placement in template
            if placement.item_id != "living-chair-west"
        ]
        if no_chair != template:
            variants.append(no_chair)
        compact_living = [
            placement
            for placement in no_chair
            if placement.item_id != "living-planter"
        ]
        if compact_living != no_chair:
            variants.append(compact_living)
        return variants
    if room.room_type != "bedroom":
        return variants
    compact: list[StylePlacement] = []
    for placement in template:
        if placement.collision_mode == "solid" and placement.asset_id not in {
            "kenney-bed-double",
            "project-modern-upholstered-bed",
        }:
            continue
        if placement.asset_id == "project-rug":
            compact.append(placement.model_copy(update={"size": (2.0, 0.05, 1.8)}))
        elif placement.asset_id in {
            "kenney-bed-double",
            "project-modern-upholstered-bed",
        }:
            compact.append(placement.model_copy(update={"size": (1.55, 1.1, 1.9)}))
        else:
            compact.append(placement)
    if compact and compact != template:
        variants.append(compact)
    return variants


def generate_layout(
    project_id: str,
    scene_revision: int,
    nodes: dict[str, dict[str, Any]],
    style: StylePack,
    asset_catalog: AssetCatalog,
) -> LayoutManifest:
    rooms = extract_rooms(nodes)
    openings, ignored_opening_ids = extract_openings(nodes, rooms)
    base = {
        "schemaVersion": "3.0",
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
        "placementSearch": "bounded-grid-v1",
        "ignoredOpeningIds": ignored_opening_ids,
        "rooms": [room.model_dump(by_alias=True, mode="json") for room in rooms],
        "openings": [opening.model_dump(by_alias=True, mode="json") for opening in openings],
    }
    if not rooms:
        payload = {
            **base,
            "status": "fallback",
            "fallbackReason": "no-room-polygon",
            "selectedRoomId": None,
            "furnishedRoomIds": [],
            "unfurnishedRoomIds": [],
            "openingBlockedRoomIds": [],
            "openingClearanceValidated": True,
            "referencedAssetBytes": 0,
            "mobileAssetBudgetBytes": asset_catalog.manifest.mobile_budget_bytes,
            "mobileAssetBudgetExceeded": False,
            "placements": [],
        }
        return LayoutManifest(layoutId=_identity_payload(payload), **payload)

    placements: list[LayoutPlacement] = []
    furnished_room_ids: list[str] = []
    unfurnished_room_ids: list[str] = []
    opening_blocked_room_ids: list[str] = []
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
                size=entry.size or asset_catalog.assets[entry.asset_id].canonical_size,
                rotationYDegrees=entry.rotation_y_degrees,
            )
            for entry in recipe
        ]
        missing_roles = sorted({entry.role for entry in template if entry.role not in style.materials})
        if missing_roles:
            raise ValueError(f"style {style.id} lacks catalog material roles: {missing_roles}")
        room_openings = [opening for opening in openings if room.id in opening.room_ids]
        translation: Point2D | None = None
        selected_template: list[StylePlacement] | None = None
        had_room_fit_candidate = False
        for variant in _template_variants(room, template):
            bounds = _item_bounds(variant)
            if not bounds or not _items_have_clearance(bounds, style.layout.item_clearance):
                raise ValueError(f"{room.room_type} asset recipe violates item clearance")
            all_points = [
                point
                for placement in variant
                if placement.collision_mode == "solid"
                for point in _rotated_corners(placement)
            ]
            template_center = (
                (min(point[0] for point in all_points) + max(point[0] for point in all_points)) / 2,
                (min(point[1] for point in all_points) + max(point[1] for point in all_points)) / 2,
            )
            candidate_translations = _candidate_translations(
                room,
                bounds,
                template_center,
                style.layout.wall_clearance,
            )
            room_fit_candidates = [
                candidate
                for candidate in candidate_translations
                if all(
                    _bounds_fit_room(item_bounds, candidate, room, style.layout.wall_clearance)
                    for item_bounds in bounds.values()
                )
            ]
            had_room_fit_candidate = had_room_fit_candidate or bool(room_fit_candidates)
            translation = next(
                (
                    candidate
                    for candidate in room_fit_candidates
                    if not any(
                        _bounds_overlap_polygon(
                            item_bounds,
                            candidate,
                            opening.clearance_polygon,
                        )
                        for item_bounds in bounds.values()
                        for opening in room_openings
                    )
                ),
                None,
            )
            if translation is not None:
                selected_template = variant
                break
        if translation is None or selected_template is None:
            if had_room_fit_candidate and room_openings:
                opening_blocked_room_ids.append(room.id)
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
            for placement in selected_template
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
        "openingBlockedRoomIds": opening_blocked_room_ids,
        "openingClearanceValidated": True,
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
