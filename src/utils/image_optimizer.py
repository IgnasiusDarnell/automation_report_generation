from pathlib import Path
from PIL import Image
import logging

logger = logging.getLogger(__name__)

def compress_image(
    image_path: Path | str,
    max_dimension: int = 1600,
    quality: int = 80
) -> Path:
    """Kompres resolusi dan kualitas gambar untuk menghemat storage."""
    target_path = Path(image_path)
    with Image.open(target_path) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        width, height = img.size
        if max(width, height) > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        img.save(target_path, "JPEG", optimize=True, quality=quality)
        logger.info(f"Compressed image: {target_path} (Quality: {quality})")
        
    return target_path
