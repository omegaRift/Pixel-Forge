"""
PIXEL FORGE - an offline pixel art generator.

Turns any JPG/PNG into retro 16x16 or 32x32 pixel art using nothing but
Pillow. No network calls, no AI models, no APIs: everything runs locally.

This is the browser version. The desktop version is pixel_forge.py; both
share the pixelation pipeline in pixel_core.py.

Run with:
    streamlit run app.py
"""

import streamlit as st
from PIL import Image

from pixel_core import GRID_OPTIONS, PREVIEW_SIZE, pixelate, to_png_bytes

# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

st.set_page_config(page_title="Pixel Forge", page_icon="👾", layout="wide")

st.title("👾 PIXEL FORGE")
st.markdown(
    "**Insert coin, upload a picture.** Pixel Forge crunches your image down "
    "to a tiny 8-bit style grid, squeezes it into a limited palette and "
    "blows it back up with razor-sharp pixels. Runs 100% offline."
)

with st.sidebar:
    st.header("🕹️ Controls")
    grid_label = st.radio("Grid Resolution", list(GRID_OPTIONS), index=0)
    grid = GRID_OPTIONS[grid_label]
    num_colors = st.slider("Color Palette Limit", min_value=2, max_value=64, value=16)
    uploaded = st.file_uploader("Upload an image", type=["jpg", "jpeg", "png"])

if uploaded is None:
    st.info("⬅️ Upload a JPG or PNG in the sidebar to start.")
    st.stop()

try:
    original = Image.open(uploaded)
    original.load()
except Exception as exc:  # corrupt or not really an image
    st.error(f"Couldn't read that file as an image: {exc}")
    st.stop()

small_art, big_art = pixelate(original, grid, num_colors)

col_orig, col_art = st.columns(2)
with col_orig:
    st.subheader("Original")
    st.image(original, width="stretch")
with col_art:
    st.subheader(f"Pixel Art ({grid}x{grid}, {num_colors} colors)")
    # Shown at its native 512px so the browser doesn't smooth-scale it.
    st.image(big_art, width=PREVIEW_SIZE)

base_name = uploaded.name.rsplit(".", 1)[0]
dl_big, dl_small = st.columns(2)
with dl_big:
    st.download_button(
        "💾 Download pixel art (512x512 PNG)",
        data=to_png_bytes(big_art),
        file_name=f"{base_name}_pixel_{grid}x{grid}.png",
        mime="image/png",
        width="stretch",
    )
with dl_small:
    st.download_button(
        f"🔬 Download raw sprite ({grid}x{grid} PNG)",
        data=to_png_bytes(small_art),
        file_name=f"{base_name}_sprite_{grid}x{grid}.png",
        mime="image/png",
        width="stretch",
    )

