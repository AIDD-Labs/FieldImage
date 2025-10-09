# Copyright (c) 2025 Eli Knodel
# Licensed under the BSD 3-Clause License. See LICENSE file for details.

import torch

from wand.image import Image as WandImage
from wand.exceptions import WandRuntimeError, WandException
from PIL import Image as PILImage, ImageOps
from pathlib import Path


def convert_and_preserve_image_metadata(input, output):
    # Creating output directory if it doesn't exist
    output_dir = output.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with WandImage(filename=input) as img:
            img.save(filename=output)
    except (WandRuntimeError, WandException) as e:
        print(f"Wand error: {e}")
    except OSError as e:
        print(f"File system error: {e}")
    except ValueError as e:
        print(f"Invalid filename: {e}")

def coord_to_decimal(tag):
    degrees, minutes, seconds = tag.values
    seconds = seconds.numerator / seconds.denominator
    decimal = degrees + (minutes / 60) + (seconds / 3600)
    return decimal

def frac_to_decimal(tag):
    frac = tag.values[0]
    decimal = frac.numerator / frac.denominator
    return decimal

def get_feature_vector(image_path, model, transform):
    """ChatGPT"""
    try:
        image = PILImage.open(image_path).convert("RGB")
        image = transform(image).unsqueeze(0)
        with torch.no_grad():
            features = model(image)
        return features.view(-1).numpy()
    except Exception as e:
        print(f"Error processing {image_path}: {e}")
        return None
    
def calc_max_pic_size(num_images, available_data):
    if num_images == 0:
        print("Total image data was already below the inputted threshold!")
        return
    else:
        return available_data / num_images

def reduce_image(image_path, target_size_mb, step=5):
    image_path = Path(image_path)
    target_size_bytes = target_size_mb * (1024 ** 2)
    quality = 100 - step

    # saving a temporary image in the same location as the original image with "_temp" added on
    temp_path = image_path.parent / f"{image_path.stem}_temp{image_path.suffix}"

    with PILImage.open(image_path) as img:
        # this ensures that image orientation is preserved
        img = ImageOps.exif_transpose(img)

        while quality > 0:
            img.save(temp_path, quality=quality)
            size_bytes = temp_path.stat().st_size
            if size_bytes <= target_size_bytes:
                break
            quality -= step

    temp_path.replace(image_path)

    return size_bytes / (1024 ** 2)