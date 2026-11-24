# LiveVAE project page

Project page for **LiveVAE: Causal Window Attention Makes Efficient Streaming Video VAE**.

Live site: https://livevae.github.io/

## Layout

```
index.html               the whole page
static/css/style.css     styles
static/js/main.js        result tabs and decoding race built from static/videos/clips.json, speed table, BibTeX copy
static/js/explainer.js   step by step animations of the Locality and Method sections
static/images/           paper figures (teaser, motivation, method overview, efficiency plots)
static/images/locality/  example frame and receptive field maps used by the Locality animation
static/explainer/        frames 0 to 32 of the streaming clip (input and LiveVAE output) as sprite sheets
tools/efficiency_plots.py  writes the three Efficiency charts into index.html
static/videos/           comparison videos, one file per clip, plus clips.json
tools/build_videos.py    builds the comparison videos and clips.json from the result folders
```

The site is plain HTML served by GitHub Pages from the `main` branch, so there is no build step. Edit `index.html` and push.

## Updating links

When the paper, code and models are public, replace the three disabled buttons in the `links` block of `index.html` with real links, for example:

```html
<a class="button" href="https://arxiv.org/abs/XXXX.XXXXX">Paper</a>
```

Then fill `\projectpageurl` in the paper's `main.tex` with the live site address above.

## Videos

Every clip is a single MP4 holding all of its panels, so the panels of a clip always
stay in sync. `tools/build_videos.py` builds them from the demo showcase folder
(`reconstruction/` and `generation/`, the raw material behind the demo deck):

```
python tools/build_videos.py --src demo_video_showcase
```

Pass `--ffmpeg PATH` if ffmpeg is not on the PATH, and `--only recon,r2v,t2v,race` to
rebuild some tasks only. The script writes `static/videos/<name>.mp4`, a poster
`<name>.jpg`, and `static/videos/clips.json`, which the page reads to fill the
Reconstruction, Reference to Video and Text to Video tabs and the decoding race.
Pick clips by editing the lists at the top of the script.

Layouts:

- Reconstruction: ground truth and LiveVAE in full on top, with the zoomed region
  marked, and one zoom tile per method below (eight methods per latent space). The
  region and the LPIPS under each tile come from the case's `info.txt`. Clips shorter
  than two seconds play slowed down to three seconds.
- Reference to video: reference image, code video, MiniMax-H3 VAE, LiveVAE in a row.
- Text to video: official VAE and LiveVAE side by side, for MiniMax-H3 and Wan2.2.
  A case listed in `T2V_ZOOM` would also get a zoom row; none is listed now.
- Decoding race (Speed section): the official and LiveVAE decodes are separate files.
  `main.js` plays each at the 720p decoder throughput from `speedData`.

`clips.json` stores a rectangle and label per panel; the page places the labels from
it. After replacing videos,
bump `assetVersion` in `main.js` so browsers do not reuse cached files.

## Explainers

`static/js/explainer.js` drives both step explainers with one player: each step is a
`.step-view` in `index.html` (title, line and duration in its data attributes) and a
draw function that renders the step at progress t from 0 to 1. Steps crossfade, and a
step opens in the state the previous one ends in, so shared drawings continue instead of
cutting. The receptive field numbers in the Locality steps come from the paper's
motivation figure. The Method steps follow the drawing and colors of the paper's method
figure: oblique latent frames with dashed links between windows (panel b) and the
streaming encoder and decoder columns (panel d). Step 4 streams the first 33 frames of a
Wan2.2 reconstruction clip (480p, 50 fps) through that diagram, using the sprite sheets in
`static/explainer/` (11 frames of 312×180 per row; ground truth input and LiveVAE output).

For generations the script prints how well the MiniMax-H3 and LiveVAE panels agree on
frame 0 and over the clip. A reference to video clip that already disagrees on frame 0
(below about 20 dB) shows its events at different moments in the two columns.
