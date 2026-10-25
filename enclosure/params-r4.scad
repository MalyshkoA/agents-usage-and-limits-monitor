// Ambient Status Bar R4 — fixes after the R3 review, millimetres. No encoder.
// build_r4.py reads every "name = number;" line below.

wall = 2.0;
fit = 0.30;

// ER-TFT3.71-1 module (datasheet). Active area assumed centred: verify on the part.
module_x = 98.89;
module_z = 25.30;
module_t = 1.60;
active_x = 91.44;
active_z = 22.86;
// Datasheet p.6: the active area is NOT centred along the length. Its border is
// 6.35 mm at the FPC end (mounted on the left) and 1.10 mm at the other end;
// 1.22 mm top and bottom.
active_border_left = 6.35;   // FPC end
active_border_right = 1.10;
active_border_z = 1.22;
gasket_t = 0.6;          // black EVA between bezel and glass
ledge = 1.2;             // support lip under the module's back edges

// Shell. Ends: the widest module border (FPC end) sets the frame, mirrored on the
// right for symmetry: 6.35 + fit 0.30 + 1.175 mm end wall = 7.825.
// Top/bottom: the minimum, 1.22 border + 0.30 fit + 0.8 bezel seat + 0.8 rim = 3.1.
frame = 7.825;
frame_z = 3.1;
body_x = 107.09;         // active_x + 2 * frame
body_y = 60.0;
face_len = 29.06;        // active_z + 2 * frame_z
screen_angle = 60.0;     // face to table
base_height = 10.5;      // front wall under the face
rear_height = 0;         // 0 = derived: the roof falls at the face-normal angle, so the
                         // rounded top corners run back as an even fillet along the roof edges
face_frame_t = 4.6;      // local face thickness: bezel recess + gasket + module + ledge
corner_radius = 4.0;     // top corners of the face and the roof/end edges; bottom stays square

// Front bezel: sits flush in a recess in the face, rim of shell around it.
bezel_t = 1.2;           // = recess depth
bezel_rim = 0.8;         // shell lip around the recess
bezel_window_margin = 0.5;
window_radius = 1.5;
pin_d = 1.6;
pin_len = 2.0;
pin_hole_d = 1.8;
// Two pins in the right end margin (the top/bottom margins are too narrow).

// Adafruit Qualia 5800 (official .brd): outline 57.15 x 44.45, M2.5 holes.
qualia_x = 57.15;
qualia_y = 44.45;
// The board is rotated 180 deg: its 40-pin FPC connector (J1) faces the left wall,
// next to where the LCD starts, and USB-C faces the free right side inside.
qualia_left = 8.00;      // outer left surface to the board's left edge: FPC bend room
qualia_front = 7.50;
j1_x = 52.451; j1_y = 26.289;   // FPC connector centre, board coordinates (.brd)
fpc_flex = 40.0;         // usable flexible length of the LCD tail
// The tail leaves the LCD's left end: no ledge there, and a niche in the left wall
// lets it fold back into the body instead of creasing on the pocket edge.
fpc_niche_wall = 1.0;    // left wall outside the niche; the tail is factory-folded behind the module
fpc_niche_depth = 3.0;   // how far the niche runs past the face frame into the body
fpc_niche_width = 22.0;  // along the LCD end, centred: the tail is ~20.5 mm wide
standoff_h = 2.0;        // underside has only solder jumpers + THT pin tails
standoff_d = 5.5;
standoff_pilot = 2.2;    // M2.5 self-tapping; 3.6 for heat-set inserts
hole1_x = 17.78; hole1_y = 10.795;
hole2_x = 17.78; hole2_y = 41.91;
hole3_x = 54.61; hole3_y = 41.91;
hole4_x = 54.61; hole4_y = 10.795;

// USB-C stays inside the enclosure; the cable leaves through the rear wall.
usb_board_x = 5.08; usb_board_y = 8.255;   // receptacle centre, board coordinates (.brd)
usb_above_board = 4.1;   // receptacle centre above the PCB underside: verify
plug_len = 28.0;         // plug overmould + strain relief beyond the board edge
plug_w = 12.5;
plug_h = 7.0;
cable_d = 5.2;           // rear cable hole; fits common 3.5-4.5 mm USB-C cables
cable_x = 89.0;          // rear notch position along the length

// Bottom cover and its four M2 corner bosses (clear of the board outline).
cover_t = 1.6;
boss_d = 6.5;
boss_h = 6.0;
boss_pilot = 1.6;        // M2 self-tapping
screw_clearance = 2.4;
boss_inset_x = 6.0;
boss_inset_y = 3.5;

// Ventilation slots in the bottom cover.
slot_w = 2.0;
slot_len = 30.0;
slot_pitch = 5.0;
