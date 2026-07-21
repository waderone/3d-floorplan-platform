from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


def parse_arguments() -> argparse.Namespace:
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Render a styled floorplan GLB")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--style", required=True, type=Path)
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--render-config", required=True, type=Path)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args(arguments)


def hex_color(value: str) -> tuple[float, float, float, float]:
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"invalid color: {value}")

    def linear(channel: int) -> float:
        srgb = channel / 255
        return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

    return (
        linear(int(value[1:3], 16)),
        linear(int(value[3:5], 16)),
        linear(int(value[5:7], 16)),
        1,
    )


def load_style(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"id", "version", "materials", "environment", "camera", "output", "layout"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise ValueError("style pack is invalid")
    return value


def load_layout(path: Path, style: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schemaVersion",
        "layoutId",
        "pipelineVersion",
        "style",
        "status",
        "openings",
        "ignoredOpeningIds",
        "openingBlockedRoomIds",
        "openingClearanceValidated",
        "placements",
    }
    if not isinstance(value, dict) or not required.issubset(value):
        raise ValueError("layout manifest is invalid")
    if (
        value["schemaVersion"] != "3.0"
        or value["pipelineVersion"] != "multiroom-opening-clearance-layout-v3"
        or value["openingClearanceValidated"] is not True
        or not isinstance(value["openings"], list)
        or not isinstance(value["ignoredOpeningIds"], list)
        or not isinstance(value["openingBlockedRoomIds"], list)
    ):
        raise ValueError("layout opening clearance contract is invalid")
    if value["style"] != {"id": style["id"], "version": style["version"]}:
        raise ValueError("layout manifest style does not match the style pack")
    if value["status"] not in {"ready", "partial", "fallback"} or not isinstance(value["placements"], list):
        raise ValueError("layout manifest status is invalid")
    return value


def load_catalog(path: Path, layout: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"schemaVersion", "id", "version", "assets"}
    if not isinstance(value, dict) or not required.issubset(value) or not isinstance(value["assets"], list):
        raise ValueError("asset catalog is invalid")
    if layout.get("assetCatalog") != {"id": value["id"], "version": value["version"]}:
        raise ValueError("layout manifest asset catalog does not match")
    assets = {
        asset["id"]: asset
        for asset in value["assets"]
        if isinstance(asset, dict) and isinstance(asset.get("id"), str)
    }
    if len(assets) != len(value["assets"]):
        raise ValueError("asset catalog ids are invalid or duplicated")
    for asset in assets.values():
        delivery = asset.get("delivery")
        if delivery is None:
            continue
        model_path = path.parent / "models" / Path(delivery["url"]).name
        content = model_path.read_bytes()
        if len(content) != delivery["bytes"] or hashlib.sha256(content).hexdigest() != delivery["sha256"]:
            raise ValueError(f"asset catalog model integrity failed: {asset['id']}")
    return value, assets


def load_render_config(
    path: Path,
    profile_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("profiles"), dict):
        raise ValueError("render profile catalog is invalid")
    profile = value["profiles"].get(profile_id)
    if not isinstance(profile, dict):
        raise ValueError(f"render profile is missing: {profile_id}")
    resources: dict[str, Path] = {}
    for resource in value.get("resources", []):
        if not isinstance(resource, dict) or not isinstance(resource.get("delivery"), dict):
            raise ValueError("render resource metadata is invalid")
        delivery = resource["delivery"]
        resource_path = (path.parent / delivery["path"]).resolve()
        content = resource_path.read_bytes()
        if (
            not resource_path.is_relative_to(path.parent.resolve())
            or len(content) != delivery["bytes"]
            or hashlib.sha256(content).hexdigest() != delivery["sha256"]
        ):
            raise ValueError(f"render resource integrity failed: {resource['id']}")
        resources[resource["id"]] = resource_path
    return value, profile, resources


def create_material(name: str, value: dict[str, Any]) -> bpy.types.Material:
    material = bpy.data.materials.new(name=f"style-{name}")
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise RuntimeError("Blender Principled BSDF node is unavailable")
    color = hex_color(value["baseColor"])
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Metallic"].default_value = float(value["metallic"])
    principled.inputs["Roughness"].default_value = float(value["roughness"])
    material.diffuse_color = color
    return material


def add_micro_bump(
    material: bpy.types.Material,
    scale: float,
    strength: float,
    distance: float,
) -> None:
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = nodes.get("Principled BSDF")
    if principled is None:
        raise RuntimeError("Blender Principled BSDF node is unavailable")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 3
    noise.inputs["Roughness"].default_value = 0.7
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], principled.inputs["Normal"])


def load_image(path: Path, non_color: bool = False) -> bpy.types.Image:
    image = bpy.data.images.load(str(path), check_existing=True)
    if non_color:
        image.colorspace_settings.name = "Non-Color"
    return image


def configure_floor_material(
    material: bpy.types.Material,
    material_set: dict[str, Any],
    resources: dict[str, Path],
    dimensions: tuple[float, float],
) -> None:
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = nodes.get("Principled BSDF")
    if principled is None:
        raise RuntimeError("Blender Principled BSDF node is unavailable")
    coordinates = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    tile_size = float(material_set["tileSizeMeters"])
    mapping.inputs["Scale"].default_value = (
        dimensions[0] / tile_size,
        dimensions[1] / tile_size,
        1,
    )
    links.new(coordinates.outputs["Generated"], mapping.inputs["Vector"])

    diffuse = nodes.new("ShaderNodeTexImage")
    diffuse.image = load_image(resources[material_set["diffuse"]])
    diffuse.extension = "REPEAT"
    roughness = nodes.new("ShaderNodeTexImage")
    roughness.image = load_image(resources[material_set["roughness"]], non_color=True)
    roughness.extension = "REPEAT"
    normal = nodes.new("ShaderNodeTexImage")
    normal.image = load_image(resources[material_set["normal"]], non_color=True)
    normal.extension = "REPEAT"
    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.inputs["Strength"].default_value = float(material_set["normalStrength"])

    for texture in (diffuse, roughness, normal):
        links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
    links.new(diffuse.outputs["Color"], principled.inputs["Base Color"])
    links.new(roughness.outputs["Color"], principled.inputs["Roughness"])
    links.new(normal.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])


def configure_world(
    world: bpy.types.World,
    environment: dict[str, Any],
    resources: dict[str, Path],
    visible_color: str,
) -> None:
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    background = nodes.get("Background")
    if background is None:
        raise RuntimeError("Blender world background node is unavailable")
    texture = nodes.new("ShaderNodeTexEnvironment")
    texture.image = load_image(resources[environment["resourceId"]])
    coordinates = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Rotation"].default_value[2] = math.radians(
        float(environment["rotationDegrees"])
    )
    links.new(coordinates.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
    links.new(texture.outputs["Color"], background.inputs["Color"])
    background.inputs["Strength"].default_value = float(environment["strength"])
    visible_background = nodes.new("ShaderNodeBackground")
    visible_background.inputs["Color"].default_value = hex_color(visible_color)
    visible_background.inputs["Strength"].default_value = 0.35
    light_path = nodes.new("ShaderNodeLightPath")
    mix = nodes.new("ShaderNodeMixShader")
    output = nodes.get("World Output")
    if output is None:
        raise RuntimeError("Blender world output node is unavailable")
    links.new(light_path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    links.new(background.outputs["Background"], mix.inputs[1])
    links.new(visible_background.outputs["Background"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])


def mesh_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("GLB contains no renderable meshes")
    minimum = Vector(tuple(min(point[index] for point in points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in points) for index in range(3)))
    return minimum, maximum


def apply_material(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)


def bevel(obj: bpy.types.Object, size: tuple[float, float, float]) -> None:
    modifier = obj.modifiers.new(name="soft-edges", type="BEVEL")
    modifier.width = min(size) * 0.08
    modifier.segments = 3
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)


def create_primitive(
    placement: dict[str, Any],
    floor_top: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    x, y, z = (float(value) for value in placement["position"])
    size = tuple(float(value) for value in placement["size"])
    blender_size = (size[0], size[2], size[1])
    location = (x, z, floor_top + y)
    kind = placement["kind"]
    if kind == "box":
        bpy.ops.mesh.primitive_cube_add(location=location)
        obj = bpy.context.object
        obj.dimensions = blender_size
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        bevel(obj, blender_size)
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=48,
            radius=max(size[0], size[2]) / 2,
            depth=size[1],
            location=location,
        )
        obj = bpy.context.object
        bevel(obj, blender_size)
    elif kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, location=location)
        obj = bpy.context.object
        obj.scale = (size[0] / 2, size[2] / 2, size[1] / 2)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    else:
        raise ValueError(f"unsupported procedural primitive: {kind}")
    obj.name = f"style-{placement['id']}"
    obj.rotation_euler[2] = math.radians(float(placement["rotationYDegrees"]))
    apply_material(obj, material)
    return obj


def create_catalog_model(
    placement: dict[str, Any],
    asset: dict[str, Any],
    catalog_path: Path,
    floor_top: float,
    soften_edges: bool,
    style_material: bpy.types.Material,
) -> list[bpy.types.Object]:
    delivery = asset.get("delivery")
    if asset.get("kind") != "model" or not isinstance(delivery, dict):
        return []
    model_path = catalog_path.parent / "models" / Path(delivery["url"]).name
    before = set(bpy.context.scene.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=str(model_path), import_shading="NORMALS")
        imported = [obj for obj in bpy.context.scene.objects if obj not in before]
        meshes = [obj for obj in imported if obj.type == "MESH"]
        if not meshes:
            raise RuntimeError("catalog GLB contains no meshes")
        if soften_edges:
            for mesh in meshes:
                modifier = mesh.modifiers.new(name="quality-edge-softening", type="BEVEL")
                modifier.width = 0.018
                modifier.segments = 2
                modifier.limit_method = "ANGLE"
        roots = [obj for obj in imported if obj.parent not in imported]
        root = bpy.data.objects.new(f"asset-{placement['id']}", None)
        bpy.context.collection.objects.link(root)
        for obj in roots:
            obj.parent = root
        width, height, depth = (float(value) for value in placement["size"])
        source_width, source_height, source_depth = (
            float(value) for value in asset["canonicalSize"]
        )
        root.scale = (
            width / source_width,
            depth / source_depth,
            height / source_height,
        )
        x, y, z = (float(value) for value in placement["position"])
        root.location = (x, z, floor_top + y - height / 2)
        root.rotation_euler[2] = math.radians(float(placement["rotationYDegrees"]))
        material_mode = asset.get("materialMode", "replace")
        if material_mode == "replace":
            for mesh in meshes:
                apply_material(mesh, style_material)
        elif material_mode == "tint":
            tint = style_material.diffuse_color
            for mesh in meshes:
                for imported_material in mesh.data.materials:
                    if imported_material is None or not imported_material.use_nodes:
                        continue
                    principled = imported_material.node_tree.nodes.get("Principled BSDF")
                    if principled is None:
                        continue
                    base_color = principled.inputs.get("Base Color")
                    if base_color is None:
                        continue
                    if base_color.is_linked:
                        source_socket = base_color.links[0].from_socket
                        imported_material.node_tree.links.remove(base_color.links[0])
                        multiply = imported_material.node_tree.nodes.new("ShaderNodeMixRGB")
                        multiply.blend_type = "MULTIPLY"
                        multiply.inputs[0].default_value = 1
                        multiply.inputs[2].default_value = tint
                        imported_material.node_tree.links.new(source_socket, multiply.inputs[1])
                        imported_material.node_tree.links.new(multiply.outputs[0], base_color)
                    else:
                        current = base_color.default_value
                        base_color.default_value = (
                            current[0] * tint[0],
                            current[1] * tint[1],
                            current[2] * tint[2],
                            current[3],
                        )
        return meshes
    except Exception:
        for obj in [obj for obj in bpy.context.scene.objects if obj not in before]:
            bpy.data.objects.remove(obj, do_unlink=True)
        return []


def point_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_area_light(name: str, location: Vector, target: Vector, color: str, energy: float) -> None:
    data = bpy.data.lights.new(name=name, type="AREA")
    data.color = hex_color(color)[:3]
    data.energy = energy
    data.shape = "DISK"
    data.size = 5
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    point_at(obj, target)


def add_baseboards(
    rooms: list[dict[str, Any]],
    floor_top: float,
    material: bpy.types.Material,
) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    for room in rooms:
        polygon = room["polygon"]
        for index, start in enumerate(polygon):
            end = polygon[(index + 1) % len(polygon)]
            start_x, start_y = float(start[0]), float(start[1])
            end_x, end_y = float(end[0]), float(end[1])
            length = math.hypot(end_x - start_x, end_y - start_y)
            if length <= 0:
                continue
            bpy.ops.mesh.primitive_cube_add(
                location=(
                    (start_x + end_x) / 2,
                    (start_y + end_y) / 2,
                    floor_top + 0.07,
                )
            )
            obj = bpy.context.object
            obj.name = f"baseboard-{room['id']}-{index}"
            obj.dimensions = (length, 0.06, 0.14)
            obj.rotation_euler[2] = math.atan2(end_y - start_y, end_x - start_x)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            bevel(obj, obj.dimensions)
            apply_material(obj, material)
            objects.append(obj)
    return objects


def add_soft_decor(
    rooms: list[dict[str, Any]],
    floor_top: float,
    materials: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    for room in rooms:
        polygon = room["polygon"]
        room_x = [float(point[0]) for point in polygon]
        room_y = [float(point[1]) for point in polygon]
        center_x = (min(room_x) + max(room_x)) / 2
        center_y = (min(room_y) + max(room_y)) / 2
        if room["roomType"] == "living":
            bpy.ops.mesh.primitive_cylinder_add(
                vertices=48,
                radius=0.1,
                depth=0.24,
                location=(center_x + 0.22, center_y - 0.1, floor_top + 0.57),
            )
            vase = bpy.context.object
            vase.name = "decor-coffee-table-vase"
            bevel(vase, (0.2, 0.2, 0.24))
            apply_material(vase, materials["ceramic"])
            objects.append(vase)
    return objects


def add_room_lights(
    rooms: list[dict[str, Any]],
    floor_top: float,
    color: str,
) -> None:
    for room in rooms:
        polygon = room["polygon"]
        room_x = [float(point[0]) for point in polygon]
        room_y = [float(point[1]) for point in polygon]
        center = Vector(
            (
                (min(room_x) + max(room_x)) / 2,
                (min(room_y) + max(room_y)) / 2,
                floor_top + 0.7,
            )
        )
        data = bpy.data.lights.new(name=f"room-softbox-{room['id']}", type="AREA")
        data.color = hex_color(color)[:3]
        data.energy = 105
        data.shape = "DISK"
        data.size = max(1.8, min(max(room_x) - min(room_x), max(room_y) - min(room_y)) * 0.55)
        obj = bpy.data.objects.new(data.name, data)
        bpy.context.collection.objects.link(obj)
        obj.location = (center.x, center.y, floor_top + 2.6)
        point_at(obj, center)


def configure_cycles_device(scene: bpy.types.Scene, preference: str) -> str:
    if preference != "METAL_PREFERRED":
        scene.cycles.device = "CPU"
        return "CPU"
    try:
        preferences = bpy.context.preferences.addons["cycles"].preferences
        preferences.compute_device_type = "METAL"
        preferences.refresh_devices()
        metal_devices = [device for device in preferences.devices if device.type == "METAL"]
        for device in preferences.devices:
            device.use = device.type == "METAL"
        if metal_devices:
            scene.cycles.device = "GPU"
            return "METAL:" + ", ".join(device.name for device in metal_devices)
    except Exception:
        pass
    scene.cycles.device = "CPU"
    return "CPU:fallback"


def position_camera(
    camera: bpy.types.Object,
    view: dict[str, Any],
    style: dict[str, Any],
    rooms: list[dict[str, Any]],
    overview_target: Vector,
    overview_radius: float,
    floor_top: float,
) -> None:
    camera.data.lens = float(view["lensMillimeters"])
    alpha = math.radians(float(view["azimuthDegrees"]))
    if view["kind"] == "overview":
        beta_degrees = float(style["camera"]["betaDegrees"])
        if len(rooms) > 1:
            beta_degrees = min(beta_degrees, 42)
        beta = math.radians(beta_degrees)
        direction = Vector(
            (
                math.cos(alpha) * math.sin(beta),
                math.sin(alpha) * math.sin(beta),
                math.cos(beta),
            )
        )
        camera.location = overview_target + direction * overview_radius
        point_at(camera, overview_target)
        return

    room = next((entry for entry in rooms if entry["roomType"] == view["roomType"]), None)
    if room is None:
        raise RuntimeError(f"render view room is unavailable: {view['roomType']}")
    room_x = [float(point[0]) for point in room["polygon"]]
    room_y = [float(point[1]) for point in room["polygon"]]
    center_x = (min(room_x) + max(room_x)) / 2
    center_y = (min(room_y) + max(room_y)) / 2
    diagonal = math.hypot(max(room_x) - min(room_x), max(room_y) - min(room_y))
    distance = diagonal * 0.43
    margin = 0.5
    camera_x = max(min(center_x + math.cos(alpha) * distance, max(room_x) - margin), min(room_x) + margin)
    camera_y = max(min(center_y + math.sin(alpha) * distance, max(room_y) - margin), min(room_y) + margin)
    camera.location = (camera_x, camera_y, floor_top + 1.55)
    point_at(camera, Vector((center_x, center_y, floor_top + 0.72)))


def configure_scene(
    style: dict[str, Any],
    layout: dict[str, Any],
    catalog_path: Path,
    assets: dict[str, dict[str, Any]],
    render_config: dict[str, Any],
    profile: dict[str, Any],
    resources: dict[str, Path],
    imported: list[bpy.types.Object],
) -> tuple[int, int, int, str, dict[str, Any]]:
    scene = bpy.context.scene
    materials = {
        role: create_material(role, value) for role, value in style["materials"].items()
    }
    if profile["engine"] == "CYCLES":
        add_micro_bump(materials["architecture"], 52, 0.11, 0.025)
        add_micro_bump(materials["fabric"], 145, 0.18, 0.012)
        add_micro_bump(materials["accent"], 90, 0.12, 0.014)
    for obj in imported:
        apply_material(obj, materials["architecture"])

    minimum, maximum = mesh_bounds(imported)
    center = (minimum + maximum) / 2
    floor_padding = float(style["layout"]["floorPadding"])
    floor_width = max(6.0, maximum.x - minimum.x + floor_padding * 2)
    floor_depth = max(6.0, maximum.y - minimum.y + floor_padding * 2)
    floor_height = 0.12
    floor_top = minimum.z
    bpy.ops.mesh.primitive_cube_add(
        location=(center.x, center.y, floor_top - floor_height / 2),
        scale=(floor_width / 2, floor_depth / 2, floor_height / 2),
    )
    floor = bpy.context.object
    floor.name = "style-floor"
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    apply_material(floor, materials["floor"])
    floor_material_set = profile.get("floorMaterialSet")
    if floor_material_set:
        configure_floor_material(
            materials["floor"],
            render_config["materialSets"][floor_material_set],
            resources,
            (floor_width, floor_depth),
        )

    furniture_meshes: list[bpy.types.Object] = []
    procedural: list[bpy.types.Object] = []
    real_asset_placements = 0
    fallback_placements = 0
    for placement in layout["placements"]:
        asset = assets.get(placement["assetId"])
        if asset is None:
            raise ValueError(f"layout references missing asset: {placement['assetId']}")
        model_meshes = create_catalog_model(
            placement,
            asset,
            catalog_path,
            floor_top,
            soften_edges=profile["engine"] == "CYCLES",
            style_material=materials[placement["role"]],
        )
        if model_meshes:
            furniture_meshes.extend(model_meshes)
            real_asset_placements += 1
            continue
        fallback = create_primitive(placement, floor_top, materials[placement["role"]])
        procedural.append(fallback)
        if asset.get("kind") == "model":
            fallback_placements += 1
    furnished_rooms = [
        room for room in layout["rooms"] if room["id"] in layout.get("furnishedRoomIds", [])
    ]
    detail_meshes = (
        add_baseboards(furnished_rooms, floor_top, materials["architecture"])
        if profile["engine"] == "CYCLES"
        else []
    )
    soft_decor = (
        add_soft_decor(furnished_rooms, floor_top, materials)
        if profile["engine"] == "CYCLES"
        else []
    )
    all_meshes = imported + [floor] + furniture_meshes + procedural + detail_meshes + soft_decor
    styled_minimum, styled_maximum = mesh_bounds(all_meshes)
    if furnished_rooms:
        room_x = [float(point[0]) for room in furnished_rooms for point in room["polygon"]]
        room_y = [float(point[1]) for room in furnished_rooms for point in room["polygon"]]
        target = Vector(
            (
                (min(room_x) + max(room_x)) / 2,
                (min(room_y) + max(room_y)) / 2,
                floor_top + max(0.8, (styled_maximum.z - floor_top) * 0.42),
            )
        )
        focus_diagonal = math.hypot(max(room_x) - min(room_x), max(room_y) - min(room_y))
    else:
        target = (styled_minimum + styled_maximum) / 2
        target.z = floor_top + max(0.8, (styled_maximum.z - floor_top) * 0.42)
        focus_diagonal = (styled_maximum - styled_minimum).length

    environment = style["environment"]
    world = bpy.data.worlds.new("style-world") if scene.world is None else scene.world
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is None:
        raise RuntimeError("Blender world background node is unavailable")
    background.inputs["Color"].default_value = hex_color(environment["backgroundColor"])
    background.inputs["Strength"].default_value = float(environment["ambientIntensity"]) * 0.32
    if profile.get("environment"):
        configure_world(
            world,
            profile["environment"],
            resources,
            environment["backgroundColor"],
        )

    radius_factor = 1.5 if len(furnished_rooms) > 1 else 0.92
    radius = max(7.0, focus_diagonal * radius_factor)
    light_factor = 0.3 if profile["engine"] == "CYCLES" else 1.0
    add_area_light(
        "style-key",
        target + Vector((radius * 0.45, -radius * 0.5, radius * 0.75)),
        target,
        environment["sunColor"],
        850 * float(environment["sunIntensity"]) * light_factor,
    )
    add_area_light(
        "style-fill",
        target + Vector((-radius * 0.55, radius * 0.35, radius * 0.42)),
        target,
        environment["ambientColor"],
        420 * float(environment["ambientIntensity"]) * light_factor,
    )
    if profile["engine"] == "CYCLES":
        add_room_lights(furnished_rooms, floor_top, environment["ambientColor"])

    camera_radius = radius * float(style["camera"]["radiusMultiplier"])
    if profile["engine"] == "CYCLES":
        camera_radius *= 1.12
    camera_data = bpy.data.cameras.new("style-camera")
    camera_data.clip_start = 0.05
    camera_data.clip_end = 250
    camera = bpy.data.objects.new("style-camera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera

    scene.render.engine = profile["engine"]
    if profile["engine"] == "BLENDER_EEVEE":
        if not hasattr(scene, "eevee"):
            raise RuntimeError("Blender 5.x EEVEE settings are unavailable")
        scene.eevee.taa_render_samples = int(profile["samples"])
        device = "RASTER"
    else:
        scene.cycles.samples = int(profile["samples"])
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = float(profile["noiseThreshold"])
        scene.cycles.use_denoising = bool(profile["denoise"])
        scene.cycles.max_bounces = 5
        scene.cycles.diffuse_bounces = 3
        scene.cycles.glossy_bounces = 3
        scene.cycles.transmission_bounces = 3
        device = configure_cycles_device(scene, profile["devicePreference"])
    scene.render.resolution_x = int(profile["width"])
    scene.render.resolution_y = int(profile["height"])
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = float(profile["exposure"])
    context = {
        "camera": camera,
        "rooms": furnished_rooms,
        "overviewTarget": target,
        "overviewRadius": camera_radius,
        "floorTop": floor_top,
    }
    return len(all_meshes), real_asset_placements, fallback_placements, device, context


def main() -> None:
    started = time.monotonic()
    args = parse_arguments()
    style = load_style(args.style)
    layout = load_layout(args.layout, style)
    catalog, assets = load_catalog(args.catalog, layout)
    render_config, profile, resources = load_render_config(args.render_config, args.profile)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input), import_shading="NORMALS")
    imported = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    object_count, real_asset_placements, fallback_placements, device, context = configure_scene(
        style,
        layout,
        args.catalog,
        assets,
        render_config,
        profile,
        resources,
        imported,
    )
    rendered_views = []
    for view in profile["views"]:
        position_camera(
            context["camera"],
            view,
            style,
            context["rooms"],
            context["overviewTarget"],
            context["overviewRadius"],
            context["floorTop"],
        )
        view_started = time.monotonic()
        output = args.output_directory / f".{view['id']}.tmp.png"
        bpy.context.scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        rendered_views.append(
            {"id": view["id"], "renderSeconds": round(time.monotonic() - view_started, 3)}
        )
    report = {
        "engine": bpy.context.scene.render.engine,
        "device": device,
        "blenderVersion": bpy.app.version_string,
        "renderSeconds": round(time.monotonic() - started, 3),
        "profileId": args.profile,
        "profileVersion": profile["version"],
        "views": rendered_views,
        "objects": object_count,
        "styleId": style["id"],
        "styleVersion": style["version"],
        "layoutId": layout["layoutId"],
        "layoutStatus": layout["status"],
        "placements": len(layout["placements"]),
        "assetCatalogId": catalog["id"],
        "assetCatalogVersion": catalog["version"],
        "realAssetPlacements": real_asset_placements,
        "fallbackPlacements": fallback_placements,
        "openingCount": len(layout["openings"]),
        "ignoredOpeningCount": len(layout["ignoredOpeningIds"]),
        "openingBlockedRoomCount": len(layout["openingBlockedRoomIds"]),
        "openingClearanceValidated": layout["openingClearanceValidated"],
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
