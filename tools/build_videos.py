"""Build the comparison videos of the project page from the demo showcase folder.

Each clip becomes one MP4 that holds every panel side by side, so the panels can never
drift apart in the browser. All panels of a clip are cut to the same number of frames.

Usage:
    python tools/build_videos.py --src demo_video_showcase [--out static/videos]
                                 [--ffmpeg ffmpeg] [--only recon,r2v,t2v,race]

--src is the showcase folder:
    reconstruction/{h3,wan22}/<case>/720p/{GT,Ours,ref_*,e2e_*,dec_*}.mp4 and info.txt
    generation/ref2v/h3/r2v_grid/<case>/{reference.png,code_video,MiniMax-H3_official,Ours}.mp4
    generation/t2v/{h3,wan22}/<group>/<case>/{<official>,Ours}.mp4

Layouts
    Reconstruction  two full frames on top (ground truth and LiveVAE) with the zoomed
                    region marked, and one zoom tile per method below. The region and
                    its LPIPS per method come from the case's info.txt. Clips shorter
                    than two seconds are slowed down to three seconds.
    Reference       reference image, code video, MiniMax-H3 VAE, LiveVAE in one row.
    Text to video   official VAE and LiveVAE side by side; a case listed in T2V_ZOOM
                    also gets a zoom row.
    Race            the official and the LiveVAE decode as two separate files; the page
                    plays them at the measured decoder throughput.

A summary of every clip (size, frames, fps, panel rectangles and labels) is written to
<out>/clips.json; the page builds its result tabs from that file. Tasks that are not
rebuilt in a run keep their entries.
"""
import argparse
import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path

GUTTER = 12                 # white gap between panels of generation clips
ACCENT = "0xb8322f"         # box colour, the page accent
FFMPEG = "ffmpeg"

RECON_METHODS = {
    "h3": [("GT", "Ground truth"), ("ref_MiniMax-H3", "MiniMax-H3"), ("e2e_TAEH3", "TAEH3"),
           ("e2e_LightVAE-Lite", "LightVAE-Lite"), ("dec_LynnReal-Omni", "LynnReal-Omni"),
           ("dec_Solar-X", "Solar-X"), ("dec_StreamRender-H3", "StreamRender-H3"),
           ("Ours", "LiveVAE (ours)")],
    "wan22": [("GT", "Ground truth"), ("ref_Wan2.2", "Wan2.2"), ("e2e_TAEW2.2", "TAEW2.2"),
              ("e2e_TAEW2.2-Super", "TAEW2.2-Super"), ("dec_LightVAE-Lite", "LightVAE-Lite"),
              ("dec_LightVAE-Pro", "LightVAE-Pro"), ("dec_Turbo-VAED", "Turbo-VAED"),
              ("Ours", "LiveVAE (ours)")],
}

# (latent space, case folder, title, where to look)
RECON = [
    ("h3", "h3_led", "Stage LED strip", "LiveVAE keeps the LED beads apart. The fast decoders merge them and the end to end models break the strip up."),
    ("h3", "h3_mesh", "Wire mesh", "LiveVAE rebuilds the diamond mesh. The fast decoders turn it into vertical stripes."),
    ("h3", "h3_blinds", "Window blinds", "The slats stay sharp and continuous with LiveVAE. They soften, turn blocky or vanish with the others."),
    ("h3", "h3_text", "Small text", "The strokes of the small logo stay smooth with LiveVAE. The end to end models lose the letter shapes."),
    ("h3", "h3_subtitle", "Subtitles", "The subtitle strokes stay legible with LiveVAE."),
    ("h3", "h3_anime", "Anime line art", "LiveVAE restores the thin whiskers of the cat."),
    ("h3", "h3_railing", "Iron railing", "The bars of the railing stay separate with LiveVAE."),
    ("h3", "h3_faces", "Face in a crowd", "The small face keeps its features with LiveVAE."),
    ("wan22", "wan_led", "Stage LED strip", "LiveVAE keeps the LED beads apart. The official Wan2.2 VAE shows horizontal banding."),
    ("wan22", "wan_brush", "Brush ferrule", "LiveVAE keeps the fine vertical ridges and the embossed mark on the metal."),
    ("wan22", "wan_anime", "Anime building", "The diagonal lines on the facade survive with LiveVAE."),
    ("wan22", "wan_tennis", "Tennis scoreboard", "The ball kids and the scoreboard digits keep their shape with LiveVAE."),
    ("wan22", "wan_faces", "Face in a crowd", "The small face keeps its features with LiveVAE."),
]

R2V = [
    ("03_gaming_01", "Gaming"),
    ("06_robotics_simulation_01_a", "Robotics simulation"),
    ("04_physical_grounding_01", "Physical grounding"),
    ("01_architectural_cinematics_01", "Architectural cinematics"),
    ("05_product_cinematography_02", "Product cinematography"),
    ("07_scene_world_editing_01_a", "Scene and world editing"),
    ("08_trajectory_variation_02_a", "Trajectory variation"),
]

T2V = {
    "h3": ("t2v_grid_h3", "MiniMax-H3_official", "MiniMax-H3", [
        ("urban_indoor_01_city_skyline", "skyline", "City skyline"),
        ("animals_01_fox_shoe", "fox", "Fox and shoe"),
        ("urban_indoor_02_golden_gate", "bridge", "Golden Gate Bridge"),
        ("nature_01_mountain_sunrise", "sunrise", "Mountain sunrise"),
        ("people_01_hand_camera", "camera", "Handing over a camera"),
        ("physics_effects_01_paintbrush", "paintbrush", "Paintbrush"),
        ("fine_detail_01_coconut_oil", "coconut", "Coconut oil"),
        ("physics_effects_02_iodine_crystals", "iodine", "Iodine crystals"),
    ]),
    "wan22": ("t2v_grid_wan22", "Wan2.2_official", "Wan2.2", [
        ("animals_02_panda", "panda", "Panda"),
        ("fast_motion_02_whale", "whale", "Whale"),
        ("fine_detail_02_coffee_milk", "coffee", "Coffee and milk"),
        ("urban_indoor_01_city_skyline", "skyline", "City skyline"),
        ("urban_indoor_02_golden_gate", "bridge", "Golden Gate Bridge"),
        ("nature_01_mountain_sunrise", "sunrise", "Mountain sunrise"),
        ("people_01_hand_camera", "camera", "Handing over a camera"),
        ("physics_effects_01_paintbrush", "paintbrush", "Paintbrush"),
    ]),
}
# Zoomed region (x, y, w, h in source pixels) for text to video clips that get a zoom row.
T2V_ZOOM = {}
T2V_NOTE = {}

# (latent space, folder under generation/t2v, case, official stem, official label)
RACE = [
    ("h3", "h3/race_h3/animals_01_fox_shoe", "MiniMax-H3_official", "MiniMax-H3 VAE"),
    ("wan22", "wan22/race_wan/animals_02_panda", "Wan2.2_official", "Wan2.2 VAE"),
]


def probe(path):
    """Return (frame count, frame rate as Fraction, width, height) of the first video stream."""
    err = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path), "-map", "0:v:0", "-c", "copy",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    w, h = map(int, re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", err).groups())
    rate = Fraction(re.search(r"([\d.]+) fps", err).group(1)).limit_denominator(1001)
    frames = int(re.findall(r"frame=\s*(\d+)", err)[-1])
    return frames, rate, w, h


def even(v):
    return int(round(v / 2) * 2)


def compose(out, width, height, rate, frames, panels, crf, poster_frame=0):
    """panels: (source path, filter chain or '', x, y). A PNG source is shown as a still."""
    inputs, chains = [], [f"color=white:s={width}x{height}:r={rate.numerator}/{rate.denominator}[b0]"]
    for i, (src, chain, x, y) in enumerate(panels):
        still = str(src).lower().endswith((".png", ".jpg"))
        inputs += (["-loop", "1"] if still else []) + ["-i", str(src)]
        steps = [f"setpts=N/({rate.numerator}/{rate.denominator})/TB"] + ([chain] if chain else []) + ["setsar=1"]
        chains.append(f"[{i}:v]{','.join(steps)}[p{i}]")
        chains.append(f"[b{i}][p{i}]overlay={x}:{y}[b{i + 1}]")
    chains.append(f"[b{len(panels)}]format=yuv420p[v]")
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains), "-map", "[v]",
         "-r", f"{rate.numerator}/{rate.denominator}", "-frames:v", str(frames),
         "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", "-an", str(out)], check=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(out), "-vf", f"select=eq(n\\,{poster_frame})",
                    "-frames:v", "1", "-q:v", "3", str(out.with_suffix(".jpg"))], check=True)


def summary(task, title, width, height, rate, frames, panels, **extra):
    return {"task": task, "title": title, "frames": frames, "fps": round(float(rate), 3),
            "seconds": round(frames / float(rate), 2), "width": width, "height": height,
            "panels": panels, **extra}


def read_box(info):
    """Zoomed region and its LPIPS per method, from a reconstruction case's info.txt."""
    text = info.read_text(encoding="utf8")
    frame, x, y, side = map(int, re.search(r"第 (\d+) 帧 \(x=(\d+), y=(\d+), 边长 (\d+)\)", text).groups())
    local = text[text.index("框 b0"):]
    lpips = {m.group(1): float(m.group(2)) for m in re.finditer(r"^\s+(\S+): ([\d.]+) / [\d.]+", local, re.M)}
    return frame, x, y, side, lpips


def build_recon(src, out_dir, space, case, title, note):
    methods = RECON_METHODS[space]
    folder = src / "reconstruction" / space / case
    files = [folder / "720p" / f"{stem}.mp4" for stem, _ in methods]
    info = [probe(f) for f in files]
    frames = min(n for n, *_ in info)
    source_rate, sw, sh = info[0][1], info[0][2], info[0][3]
    # Very short clips loop too fast to inspect, so they play in slow motion.
    rate = source_rate if frames / source_rate >= 2 else Fraction(frames, 3).limit_denominator(100)
    box_frame, bx, by, side, lpips = read_box(folder / "info.txt")

    n, gap = len(methods), 8
    tile = 256
    width = n * tile + (n - 1) * gap
    fw = (width - gap) // 2
    fh = even(fw * sh / sw)
    height = fh + gap + tile
    k = fw / sw
    # Box on the full frames: accent outside, white inside, clipped to the frame.
    def box(pad, colour, t):
        x0, y0 = max(0, round(bx * k) - pad), max(0, round(by * k) - pad)
        x1, y1 = min(fw, round((bx + side) * k) + pad), min(fh, round((by + side) * k) + pad)
        return f"drawbox=x={x0}:y={y0}:w={x1 - x0}:h={y1 - y0}:color={colour}:t={t}"
    full = f"scale={fw}:{fh}:flags=lanczos,{box(6, ACCENT, 4)},{box(2, 'white', 2)}"
    zoom = f"crop={side}:{side}:{bx}:{by},scale={tile}:{tile}:flags=bicubic"

    panels = [(files[0], full, 0, 0), (files[-1], full, fw + gap, 0)]
    meta = [{"label": "Ground truth", "rect": [0, 0, fw, fh]},
            {"label": "LiveVAE (ours)", "rect": [fw + gap, 0, fw, fh], "ours": True}]
    for i, (f, (stem, label)) in enumerate(zip(files, methods)):
        x = i * (tile + gap)
        panels.append((f, zoom, x, fh + gap))
        entry = {"label": label, "rect": [x, fh + gap, tile, tile], "zoom": True}
        if stem in lpips:
            entry["sub"] = f"LPIPS {lpips[stem]:.3f}"
        if stem == "Ours":
            entry["ours"] = True
        meta.append(entry)

    name = f"recon_{space}_{case.split('_', 1)[1]}"
    poster = min(box_frame, frames - 1)
    compose(out_dir / f"{name}.mp4", width, height, rate, frames, panels, crf=18, poster_frame=poster)
    s = summary(f"recon_{space}", title, width, height, rate, frames, meta, note=note,
                resolution="720p", source_fps=round(float(source_rate), 3), mark_frame=poster)
    print(f"{name}: {frames} frames, {float(source_rate):.2f} fps source, shown at {float(rate):.2f} fps")
    return name, s


def build_r2v(src, out_dir, case, title):
    folder = src / "generation" / "ref2v" / "h3" / "r2v_grid" / case
    cols = [("reference.png", "Reference image"), ("code_video.mp4", "Code video"),
            ("MiniMax-H3_official.mp4", "MiniMax-H3"), ("Ours.mp4", "LiveVAE (ours)")]
    videos = [probe(folder / f) for f, _ in cols[1:]]
    frames = min(n for n, *_ in videos)
    rate = videos[-1][1]
    pw, ph = 720, 408
    width = len(cols) * pw + (len(cols) - 1) * GUTTER
    panels, meta = [], []
    for i, (f, label) in enumerate(cols):
        x = i * (pw + GUTTER)
        # The reference image is 16:9, the generations 30:17; crop the image to match.
        chain = (f"scale={pw}:{ph}:force_original_aspect_ratio=increase:flags=lanczos,crop={pw}:{ph}"
                 if i == 0 else f"scale={pw}:{ph}:flags=lanczos")
        panels.append((folder / f, chain, x, 0))
        meta.append({"label": label, "rect": [x, 0, pw, ph], **({"ours": True} if i == 3 else {})})
    name = "r2v_" + re.sub(r"^\d+_", "", case)
    compose(out_dir / f"{name}.mp4", width, ph, rate, frames, panels, crf=22)
    print(f"{name}: {frames} frames at {float(rate):.2f} fps")
    return name, summary("r2v", title, width, ph, rate, frames, meta)


def build_t2v(src, out_dir, space, group, official, official_label, case, short, title):
    folder = src / "generation" / "t2v" / space / group / case
    files = [folder / f"{official}.mp4", folder / "Ours.mp4"]
    info = [probe(f) for f in files]
    frames = min(n for n, *_ in info)
    rate, sw, sh = info[0][1], info[0][2], info[0][3]
    pw, ph = even(sw * .75), even(sh * .75)
    width = 2 * pw + GUTTER
    name = f"t2v_{space}_{short}"
    labels = [official_label, "LiveVAE (ours)"]
    panels = [(f, f"scale={pw}:{ph}:flags=lanczos", i * (pw + GUTTER), 0) for i, f in enumerate(files)]
    meta = [{"label": l, "rect": [i * (pw + GUTTER), 0, pw, ph], **({"ours": True} if i else {})}
            for i, l in enumerate(labels)]
    height, extra = ph, {}
    if name in T2V_ZOOM:
        zx, zy, zw, zh = T2V_ZOOM[name]
        k = pw / sw
        def box(pad, colour, t):
            return (f"drawbox=x={round(zx * k) - pad}:y={round(zy * k) - pad}:w={round(zw * k) + 2 * pad}"
                    f":h={round(zh * k) + 2 * pad}:color={colour}:t={t}")
        panels = [(f, f"{c},{box(5, ACCENT, 3)},{box(2, 'white', 2)}", x, y) for f, c, x, y in panels]
        for i, f in enumerate(files):
            x = i * (pw + GUTTER)
            panels.append((f, f"crop={zw}:{zh}:{zx}:{zy},scale={pw}:{ph}:flags=bicubic", x, ph + GUTTER))
            meta.append({"label": labels[i] + ", zoomed", "rect": [x, ph + GUTTER, pw, ph],
                         **({"ours": True} if i else {})})
        height = 2 * ph + GUTTER
        extra = {"note": T2V_NOTE.get(name, "")}
    compose(out_dir / f"{name}.mp4", width, height, rate, frames, panels, crf=21)
    print(f"{name}: {frames} frames at {float(rate):.2f} fps")
    return name, summary(f"t2v_{space}", title, width, height, rate, frames, meta, **extra)


def build_race(src, out_dir, space, rel, official, official_label):
    folder = src / "generation" / "t2v" / rel
    files = [folder / f"{official}.mp4", folder / "Ours.mp4"]
    info = [probe(f) for f in files]
    frames = min(n for n, *_ in info)
    rate, sw, sh = info[0][1], info[0][2], info[0][3]
    pw, ph = even(sw * .75), even(sh * .75)
    names = [f"race_{space}_official", f"race_{space}_ours"]
    for f, n in zip(files, names):
        compose(out_dir / f"{n}.mp4", pw, ph, rate, frames, [(f, f"scale={pw}:{ph}:flags=lanczos", 0, 0)], crf=22)
    print(f"race_{space}: {frames} frames at {float(rate):.2f} fps")
    return f"race_{space}", {"task": "race", "model": space, "frames": frames, "fps": round(float(rate), 3),
                             "width": pw, "height": ph, "files": names,
                             "labels": [official_label + " (official)", "LiveVAE"]}


def main():
    global FFMPEG
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("static/videos"))
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--only", default="recon,r2v,t2v,race")
    args = ap.parse_args()
    FFMPEG = args.ffmpeg
    only = set(args.only.split(","))
    args.out.mkdir(parents=True, exist_ok=True)

    manifest = args.out / "clips.json"
    clips = json.loads(manifest.read_text()) if manifest.exists() else {}
    clips = {k: v for k, v in clips.items() if v["task"].split("_")[0] not in only}
    if "recon" in only:
        for row in RECON:
            name, s = build_recon(args.src, args.out, *row)
            clips[name] = s
    if "r2v" in only:
        for row in R2V:
            name, s = build_r2v(args.src, args.out, *row)
            clips[name] = s
    if "t2v" in only:
        for space, (group, official, label, cases) in T2V.items():
            for row in cases:
                name, s = build_t2v(args.src, args.out, space, group, official, label, *row)
                clips[name] = s
    if "race" in only:
        for row in RACE:
            name, s = build_race(args.src, args.out, *row)
            clips[name] = s
    order = ["recon_h3", "recon_wan22", "r2v", "t2v_h3", "t2v_wan22", "race"]
    clips = dict(sorted(clips.items(), key=lambda kv: order.index(kv[1]["task"])))
    manifest.write_text(json.dumps(clips, indent=2) + "\n")


if __name__ == "__main__":
    main()
