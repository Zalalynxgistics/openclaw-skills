#!/usr/bin/env python3
"""Crop an input image to a 300x300 square headshot for org chart."""
import sys
from PIL import Image

def crop_headshot(input_path, output_path):
    img = Image.open(input_path)
    w, h = img.size
    crop_size = min(w, h) * 0.65
    cx = w / 2
    cy = h * 0.32  # face typically in upper portion
    left = max(0, cx - crop_size / 2)
    top = max(0, cy - crop_size / 2)
    right = min(w, cx + crop_size / 2)
    bottom = min(h, cy + crop_size / 2)
    # Make square
    box_w, box_h = right - left, bottom - top
    if box_w > box_h:
        d = (box_w - box_h) / 2; left += d; right -= d
    elif box_h > box_w:
        d = (box_h - box_w) / 2; top += d; bottom -= d
    cropped = img.crop((int(left), int(top), int(right), int(bottom)))
    cropped = cropped.resize((300, 300), Image.LANCZOS)
    cropped.save(output_path, quality=90)
    print(f"Saved: {output_path} (300x300)")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_image> <output.jpg>")
        sys.exit(1)
    crop_headshot(sys.argv[1], sys.argv[2])
