#!/usr/bin/env python3
"""Build R4: R3's low wedge, fixed after review. No encoder.

- one visible frame width (5.2 mm) on all four sides of the active area; the body
  is sized for the real 98.89 x 25.30 mm module (R3 only fitted the active area);
- the module drops into a pocket in the 60 deg face onto a 1.2 mm ledge; the front
  bezel sits flush in a recess in the face (gasket in between), located by pins;
- top corners of the face, and the roof/end edges behind them, are rounded;
  the bottom corners stay square so they meet the front wall cleanly;
- Qualia sits on four standoffs at its M2.5 holes;
- the bottom cover screws into four corner bosses that clear the board;
- USB-C gets an outer recess so a plug overmould reaches the receptacle;
- vent slots in the bottom cover.

Also checks that the board, the module and the bezel do not collide with printed parts,
and writes an assembled preview (.glb with colours, .stl).
"""
import math
import re
from pathlib import Path

import manifold3d
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent
EXPORTS = ROOT / "exports-r4"


def params():
    result = {}
    pattern = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(-?[0-9.]+)\s*;")
    for line in (ROOT / "params-r4.scad").read_text().splitlines():
        code = line.split("//")[0]
        for match in pattern.finditer(code):
            result[match.group(1)] = float(match.group(2))
    return result


P = params()
W, D = P["body_x"], P["body_y"]
L = P["face_len"]
TILT = 90.0 - P["screen_angle"]
FACE_RUN = L * math.cos(math.radians(P["screen_angle"]))
FACE_RISE = L * math.sin(math.radians(P["screen_angle"]))
PEAK_Y, PEAK_Z = FACE_RUN, P["base_height"] + FACE_RISE
R = P["corner_radius"]
# Roof parallel to the face normal: every roof point then sits at the top edge of
# the face outline, so the top-corner rounding becomes one even fillet.
REAR_H = P["rear_height"] or PEAK_Z - math.tan(math.radians(TILT)) * (D - PEAK_Y)
RIM = P["bezel_rim"]
BEZEL_W, BEZEL_L = W - 2 * RIM, L - 2 * RIM
POCKET_X = P["module_x"] + 2 * P["fit"]
POCKET_Z = P["module_z"] + 2 * P["fit"]
# The pocket follows the real active-area position (datasheet): the active area
# is centred in the body, the module is not.
POCKET_X0 = P["frame"] - P["active_border_left"] - P["fit"]
POCKET_Z0 = P["frame_z"] - P["active_border_z"] - P["fit"]
ACTIVE_X0 = POCKET_X0 + P["fit"] + P["active_border_left"]
ACTIVE_Z0 = POCKET_Z0 + P["fit"] + P["active_border_z"]
assert abs(W - (P["active_x"] + 2 * P["frame"])) < 0.01, "body_x must equal active_x + 2 * frame"
assert abs(L - (P["active_z"] + 2 * P["frame_z"])) < 0.01, "face_len must equal active_z + 2 * frame_z"
assert abs(P["module_x"] - P["active_x"] - P["active_border_left"] - P["active_border_right"]) < 0.01
MODULE_FRONT = P["bezel_t"] + P["gasket_t"]          # depth of the glass below the face
POCKET_DEPTH = MODULE_FRONT + P["module_t"]          # depth of the ledge
# Bezel pins in the right end margin, between the pocket and the recess edge.
PINS = [((POCKET_X0 + POCKET_X + W - RIM) / 2, u) for u in (L / 3, 2 * L / 3)]
BOARD_Z0 = P["cover_t"] + P["standoff_h"]
CABLE_R = P["cable_d"] / 2
CABLE_Z = P["cover_t"] + CABLE_R + 0.6


def board_point(bx, by):
    """Board (.brd) coordinates -> enclosure XY. The board is rotated 180 deg so J1
    faces the left wall and USB-C faces the free right side."""
    return (P["qualia_left"] + P["qualia_x"] - bx, P["qualia_front"] + P["qualia_y"] - by)


J1_X, J1_Y = board_point(P["j1_x"], P["j1_y"])
USB_X, USB_Y = board_point(P["usb_board_x"], P["usb_board_y"])
USB_Z = BOARD_Z0 + P["usb_above_board"]
BOARD_RIGHT = P["qualia_left"] + P["qualia_x"]


def box(size, center):
    mesh = trimesh.creation.box(extents=size)
    mesh.apply_translation(center)
    return mesh


def box_span(x0, x1, y0, y1, z0, z1):
    return box([x1 - x0, y1 - y0, z1 - z0], [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])


def cylinder(diameter, length, center, axis):
    mesh = trimesh.creation.cylinder(radius=diameter / 2, height=length, sections=48)
    if axis == "x":
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    elif axis == "y":
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    mesh.apply_translation(center)
    return mesh


def union(*meshes):
    return trimesh.boolean.union(list(meshes), engine="manifold")


def subtract(base, *cuts):
    return trimesh.boolean.difference([base, *cuts], engine="manifold")


def intersect(a, b):
    return trimesh.boolean.intersection([a, b], engine="manifold")


def to_mesh(manifold):
    raw = manifold.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(raw.vert_properties)[:, :3],
                           faces=np.asarray(raw.tri_verts), process=True)


def rect(x0, x1, y0, y1):
    return manifold3d.CrossSection([[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]])


def circle(cx, cy, r):
    return manifold3d.CrossSection.circle(r, 64).translate((cx, cy))


def top_rounded(x0, x1, y0, y1, r):
    """2D rectangle whose two top corners are rounded and bottom corners square."""
    return (rect(x0, x1, y0, y1 - r) + rect(x0 + r, x1 - r, y0, y1)
            + circle(x0 + r, y1 - r, r) + circle(x1 - r, y1 - r, r))


def rounded(x0, x1, y0, y1, r):
    return (rect(x0 + r, x1 - r, y0, y1) + rect(x0, x1, y0 + r, y1 - r)
            + circle(x0 + r, y0 + r, r) + circle(x1 - r, y0 + r, r)
            + circle(x0 + r, y1 - r, r) + circle(x1 - r, y1 - r, r))


def face_prism(section, y0, y1):
    """Extrude a face-plane outline (x along the length, y up the slope) through
    face-local depth y0..y1 (positive = into the body) and place it in the world."""
    mesh = to_mesh(section.extrude(y1 - y0))
    # (x, u, depth) -> face-local (x, depth, u)
    mesh.vertices = mesh.vertices[:, [0, 2, 1]] + [0, y0, 0]
    mesh.invert()  # the axis swap mirrors the mesh; restore outward normals
    return face(mesh)


def flat_prism(section, z0, z1):
    mesh = to_mesh(section.extrude(z1 - z0))
    mesh.apply_translation([0, 0, z0])
    return mesh


def prism_x(cross_section, x0, width):
    raw = cross_section.extrude(width).to_mesh()
    # manifold (Y, Z, extrusion) -> project (X, Y, Z)
    vertices = np.asarray(raw.vert_properties)[:, :3][:, [2, 0, 1]]
    vertices[:, 0] += x0
    return trimesh.Trimesh(vertices=vertices, faces=np.asarray(raw.tri_verts), process=True)


def face(mesh):
    """Face-local (x along length, y into the body, z up the slope) -> world."""
    mesh = mesh.copy()
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(-TILT), [1, 0, 0]))
    mesh.apply_translation([0, 0, P["base_height"]])
    return mesh


OUTER_POLY = [(0, 0), (D, 0), (D, REAR_H), (PEAK_Y, PEAK_Z), (0, P["base_height"])]


def outer_body():
    wedge = prism_x(manifold3d.CrossSection([OUTER_POLY]), 0, W)
    # Round the top face corners and carry them back along the roof/end edges:
    # keep everything except the two strips above the face's top corners.
    keep = top_rounded(0, W, -200, L, R) + rect(R, W - R, -200, 200)
    return intersect(wedge, face_prism(keep, -100, 200))


def shell():
    w = P["wall"]
    outer = outer_body()
    cavity = manifold3d.CrossSection([OUTER_POLY]).offset(-w, manifold3d.JoinType.Miter)
    cavity = cavity + rect(w, D - w, -1, w + 1)
    body = subtract(outer, prism_x(cavity, w, W - 2 * w))

    # Thickened face that hosts the bezel recess, the module pocket and its ledge.
    frame = intersect(face(box_span(0, W, 0, P["face_frame_t"], 0, L)), outer)
    bosses = []
    for x in (P["boss_inset_x"], W - P["boss_inset_x"]):
        for y in (P["boss_inset_y"], D - P["boss_inset_y"]):
            bosses.append(cylinder(P["boss_d"], P["boss_h"], [x, y, P["cover_t"] + P["boss_h"] / 2], "z"))
    body = union(body, frame, intersect(union(*bosses), outer))

    cuts = [
        # Recess so the bezel sits flush with the face, rim of shell around it.
        face_prism(top_rounded(RIM, W - RIM, RIM, L - RIM, R - RIM), -1, P["bezel_t"]),
        # Module pocket, then the through-opening behind it, smaller by the ledge.
        face(box_span(POCKET_X0, POCKET_X0 + POCKET_X, -1, POCKET_DEPTH,
                      POCKET_Z0, POCKET_Z0 + POCKET_Z)),
        face(box_span(POCKET_X0 + P["ledge"], POCKET_X0 + POCKET_X - P["ledge"],
                      POCKET_DEPTH - 0.01, P["face_frame_t"] + 1,
                      POCKET_Z0 + P["ledge"], POCKET_Z0 + POCKET_Z - P["ledge"])),
    ]
    # Niche for the LCD tail at the left end: removes the left ledge and thins the
    # left wall behind the glass so the tail can fold back without a hard crease.
    cuts.append(face(box_span(P["fpc_niche_wall"], POCKET_X0 + P["ledge"] + 3.0,
                              MODULE_FRONT, P["face_frame_t"] + P["fpc_niche_depth"],
                              POCKET_Z0 + POCKET_Z / 2 - P["fpc_niche_width"] / 2,
                              POCKET_Z0 + POCKET_Z / 2 + P["fpc_niche_width"] / 2)))
    hole_len = P["pin_len"] + 0.6
    for x, u in PINS:
        cuts.append(face(cylinder(P["pin_hole_d"], hole_len,
                                  [x, P["bezel_t"] + hole_len / 2 - 0.05, u], "y")))
    for x in (P["boss_inset_x"], W - P["boss_inset_x"]):
        for y in (P["boss_inset_y"], D - P["boss_inset_y"]):
            cuts.append(cylinder(P["boss_pilot"], P["boss_h"] - 1, [x, y, P["cover_t"] + (P["boss_h"] - 1) / 2 - 0.05], "z"))
    # Rear cable notch, open at the bottom: with the cover off the cable is laid in
    # from below; the cover's tab then closes it into a round hole.
    cx = P["cable_x"]
    cuts.append(box_span(cx - CABLE_R, cx + CABLE_R, D - w - 0.5, D + 0.5, -1, CABLE_Z))
    cuts.append(cylinder(P["cable_d"], w + 1, [cx, D - w / 2, CABLE_Z], "y"))
    return subtract(body, *cuts)


def board_holes():
    for i in range(1, 5):
        yield board_point(P[f"hole{i}_x"], P[f"hole{i}_y"])


def bottom_cover():
    w, fit, t = P["wall"], P["fit"], P["cover_t"]
    plate = box_span(w + fit, W - w - fit, w + fit, D - w - fit, 0, t)
    standoffs = [cylinder(P["standoff_d"], P["standoff_h"], [x, y, t + P["standoff_h"] / 2], "z")
                 for x, y in board_holes()]
    # Tab that fills the rear notch up to a cradle for the cable.
    cx = P["cable_x"]
    tab = subtract(box_span(cx - CABLE_R + 0.15, cx + CABLE_R - 0.15, D - w - fit - 0.5, D, 0, CABLE_Z),
                   cylinder(P["cable_d"], w + fit + 2, [cx, D - (w + fit) / 2, CABLE_Z], "y"))
    body = union(plate, tab, *standoffs)
    cuts = [cylinder(P["standoff_pilot"], P["standoff_h"] + 1, [x, y, t + (P["standoff_h"] + 1) / 2 - 0.9], "z")
            for x, y in board_holes()]
    for x in (P["boss_inset_x"], W - P["boss_inset_x"]):
        for y in (P["boss_inset_y"], D - P["boss_inset_y"]):
            cuts.append(cylinder(P["screw_clearance"], t + 0.4, [x, y, t / 2], "z"))
    # Vents: under the free right end and between the board standoffs.
    x = BOARD_RIGHT + 6
    while x <= W - P["boss_inset_x"] - 6:
        cuts.append(box([P["slot_w"], P["slot_len"], t + 0.4], [x, D / 2, t / 2]))
        x += P["slot_pitch"]
    board_mid_y = P["qualia_front"] + P["qualia_y"] / 2
    keep_clear = P["standoff_d"] / 2 + 1.0   # never cut the plate under a standoff
    x = P["qualia_left"] + 9
    while x <= BOARD_RIGHT - 9:
        y0, y1 = board_mid_y - 10, board_mid_y + 10
        clear = all(abs(hx - x) > keep_clear + P["slot_w"] / 2 or not (y0 - keep_clear < hy < y1 + keep_clear)
                    for hx, hy in board_holes())
        if clear:
            cuts.append(box([P["slot_w"], y1 - y0, t + 0.4], [x, board_mid_y, t / 2]))
        x += P["slot_pitch"]
    return subtract(body, *cuts)


def screen_bezel():
    """Printed flat, front face on the bed (Z=0), pins up. Flat X runs right-to-left
    as seen from the front, so length offsets are mirrored."""
    t = P["bezel_t"]
    plate = flat_prism(top_rounded(0, BEZEL_W, 0, BEZEL_L, R - RIM), 0, t)
    win_w = P["active_x"] + 2 * P["bezel_window_margin"]
    win_h = P["active_z"] + 2 * P["bezel_window_margin"]
    # Window centred on the real active area; flat X is mirrored (printed face-down).
    cx = (W - RIM) - (ACTIVE_X0 + P["active_x"] / 2)
    cy = (ACTIVE_Z0 + P["active_z"] / 2) - RIM
    window = flat_prism(rounded(cx - win_w / 2, cx + win_w / 2, cy - win_h / 2, cy + win_h / 2,
                                P["window_radius"]), -0.2, t + 0.2)
    pins = [cylinder(P["pin_d"], P["pin_len"], [BEZEL_W - (x - RIM), u - RIM, t + P["pin_len"] / 2], "z")
            for x, u in PINS]
    return union(subtract(plate, window), *pins)


def bezel_in_place(bezel):
    # flat (X, Y, Z) -> face-local (x = W - RIM - X, depth = Z, u = Y + RIM)
    placed = bezel.copy()
    placed.apply_transform(np.array([[-1, 0, 0, W - RIM], [0, 0, 1, 0], [0, 1, 0, RIM], [0, 0, 0, 1]], dtype=float))
    return face(placed)


def module_in_place():
    return face(box_span(POCKET_X0 + P["fit"], POCKET_X0 + P["fit"] + P["module_x"],
                         MODULE_FRONT, POCKET_DEPTH,
                         POCKET_Z0 + P["fit"], POCKET_Z0 + P["fit"] + P["module_z"]))


def plug_envelope():
    return box_span(BOARD_RIGHT, BOARD_RIGHT + P["plug_len"],
                    USB_Y - P["plug_w"] / 2, USB_Y + P["plug_w"] / 2,
                    USB_Z - P["plug_h"] / 2, USB_Z + P["plug_h"] / 2)


def j1_marker():
    return box_span(J1_X - 2.5, J1_X + 2.5, J1_Y - 12, J1_Y + 12, BOARD_Z0 + 1.6, BOARD_Z0 + 4.1)


def active_area_in_place():
    """The lit pixels, extruded from the glass to the viewer, must stay uncovered."""
    return face(box_span(ACTIVE_X0, ACTIVE_X0 + P["active_x"], -2, MODULE_FRONT,
                         ACTIVE_Z0, ACTIVE_Z0 + P["active_z"]))


def check_fit(parts):
    parts = dict(parts, **{"bezel-in-place": bezel_in_place(parts["screen-bezel"])})
    board = box_span(P["qualia_left"], P["qualia_left"] + P["qualia_x"],
                     P["qualia_front"], P["qualia_front"] + P["qualia_y"],
                     BOARD_Z0, BOARD_Z0 + 7.1)
    checks = (("Qualia envelope", board, ("low-wedge-shell", "bottom-cover-pcb-tray")),
              ("LCD module", module_in_place(), ("low-wedge-shell", "bottom-cover-pcb-tray")),
              ("bezel in recess", bezel_in_place(parts["screen-bezel"]), ("low-wedge-shell",)),
              ("USB-C plug", plug_envelope(), ("low-wedge-shell", "bottom-cover-pcb-tray")),
              ("active area", active_area_in_place(), ("bezel-in-place", "low-wedge-shell")))
    for label, envelope, against in checks:
        for name in against:
            overlap = intersect(parts[name], envelope)
            volume = overlap.volume if len(overlap.faces) else 0.0
            status = "ok" if volume < 1.0 else "COLLISION"
            print(f"  {label:16s} vs {name:22s}: {volume:7.2f} mm3 {status}")
    # Straight-line reach from the LCD's lower-left back corner to J1 (the real
    # path also bends up from J1 along the left wall).
    lcd_corner = face(trimesh.Trimesh(vertices=[[POCKET_X0 + P["fit"] + 3, POCKET_DEPTH, POCKET_Z0 + P["fit"] + 3]],
                                      faces=np.zeros((0, 3), dtype=int))).vertices[0]
    j1 = np.array([J1_X, J1_Y, BOARD_Z0 + 2.5])
    reach = float(np.linalg.norm(j1 - lcd_corner))
    print(f"  FPC reach LCD corner -> J1: {reach:.1f} mm straight "
          f"(flex budget {P['fpc_flex']:.0f} mm) {'ok' if reach < P['fpc_flex'] - 8 else 'CHECK'}")


def assembly(parts):
    """Everything in place, for viewing only: bezel in its recess, cover in the
    bottom, plus dummy Qualia and LCD blocks. Coloured parts in a .glb."""
    board = box_span(P["qualia_left"], P["qualia_left"] + P["qualia_x"],
                     P["qualia_front"], P["qualia_front"] + P["qualia_y"],
                     BOARD_Z0, BOARD_Z0 + 1.6)
    colours = {
        "shell": (parts["low-wedge-shell"], [36, 39, 42, 255]),
        "bottom-cover": (parts["bottom-cover-pcb-tray"], [59, 63, 68, 255]),
        "bezel": (bezel_in_place(parts["screen-bezel"]), [24, 26, 28, 255]),
        "qualia-dummy": (board, [63, 140, 87, 255]),
        "fpc-connector-j1": (j1_marker(), [235, 235, 235, 255]),
        "usb-c-plug": (plug_envelope(), [150, 150, 150, 255]),
        "lcd-dummy": (module_in_place(), [30, 60, 120, 255]),
    }
    scene = trimesh.Scene()
    for name, (mesh, rgba) in colours.items():
        mesh = mesh.copy()
        mesh.visual.face_colors = rgba
        scene.add_geometry(mesh, geom_name=name)
    scene.export(EXPORTS / "asb-r4-assembly-preview.glb")
    trimesh.util.concatenate([m for m, _ in colours.values()]).export(EXPORTS / "asb-r4-assembly-preview.stl")

    # Exploded along the face normal, in assembly order: module, gasket, bezel.
    outward = np.array([0.0, -math.cos(math.radians(TILT)), math.sin(math.radians(TILT))])
    gasket = subtract(
        face(box_span(POCKET_X0 + P["fit"], POCKET_X0 + P["fit"] + P["module_x"], P["bezel_t"], MODULE_FRONT,
                      POCKET_Z0 + P["fit"], POCKET_Z0 + P["fit"] + P["module_z"])),
        face(box_span(0, W, -1, 10, L / 2 - P["active_z"] / 2 - P["bezel_window_margin"],
                      L / 2 + P["active_z"] / 2 + P["bezel_window_margin"])))
    exploded = trimesh.Scene()
    for name, mesh, rgba, lift in (
        ("shell", parts["low-wedge-shell"], [36, 39, 42, 255], 0),
        ("bottom-cover", parts["bottom-cover-pcb-tray"], [59, 63, 68, 255], 0),
        ("qualia-dummy", board, [63, 140, 87, 255], 0),
        ("fpc-connector-j1", j1_marker(), [235, 235, 235, 255], 0),
        ("usb-c-plug", plug_envelope(), [150, 150, 150, 255], 0),
        ("lcd-dummy", module_in_place(), [30, 110, 220, 255], 12),
        ("gasket", gasket, [242, 153, 0, 255], 22),
        ("bezel", bezel_in_place(parts["screen-bezel"]), [194, 24, 91, 255], 32),
    ):
        mesh = mesh.copy()
        mesh.apply_translation(outward * lift)
        mesh.visual.face_colors = rgba
        exploded.add_geometry(mesh, geom_name=name)
    exploded.export(EXPORTS / "asb-r4-exploded-preview.glb")


PARTS = {"low-wedge-shell": shell, "bottom-cover-pcb-tray": bottom_cover, "screen-bezel": screen_bezel}


def main():
    EXPORTS.mkdir(exist_ok=True)
    built = {}
    for name, builder in PARTS.items():
        mesh = builder()
        if not mesh.is_watertight:
            raise RuntimeError(f"{name} is not watertight")
        mesh.export(EXPORTS / f"asb-r4-{name}.stl")
        built[name] = mesh
        print(f"{name:24s} faces={len(mesh.faces):6d} volume={mesh.volume:9.1f} "
              f"extents={[round(float(v), 2) for v in mesh.extents]}")
    left, right = ACTIVE_X0, W - (ACTIVE_X0 + P["active_x"])
    bottom, top = ACTIVE_Z0, L - (ACTIVE_Z0 + P["active_z"])
    print(f"overall: {W:.2f} x {D:.2f} x {PEAK_Z:.2f} mm, rear wall {REAR_H:.2f} mm, face {P['screen_angle']:.0f} deg, "
          f"visible frame L {left:.2f} / R {right:.2f} / T {top:.2f} / B {bottom:.2f} mm")
    check_fit(built)
    assembly(built)
    print("assembly preview: exports-r4/asb-r4-assembly-preview.glb (.stl)")


if __name__ == "__main__":
    main()
