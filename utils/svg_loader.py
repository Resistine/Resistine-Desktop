import os
import io
import sys
from PIL import Image
import customtkinter

try:
    import cairosvg
except ImportError:
    cairosvg = None

def load_svg_as_ctk_image(svg_path, size=None):
    """
    Load an SVG file, convert it to a PIL Image using cairosvg, 
    and return a customtkinter.CTkImage.
    
    Args:
        svg_path (str): Absolute path to the SVG file.
        size (tuple): (width, height) tuple for the final display size.
        
    Returns:
        customtkinter.CTkImage: The loaded image, or None if loading failed.
    """
    if not os.path.exists(svg_path):
        return None
        
    if cairosvg is None:
        print("cairosvg not installed, cannot load SVG.")
        return None

    try:
        # We need a target size for rasterization. 
        # If size is provided, use it (maybe x2 for high DPI).
        # implementing a simple 2x scaling for better quality
        scale_factor = 2
        output_width = size[0] * scale_factor if size else None
        output_height = size[1] * scale_factor if size else None
            
        # Convert SVG content to PNG data in memory
        png_data = cairosvg.svg2png(
            url=svg_path,
            output_width=output_width,
            output_height=output_height
        )
        
        # Open as PIL Image
        image = Image.open(io.BytesIO(png_data))
        
        return customtkinter.CTkImage(
            light_image=image,
            dark_image=image,
            size=size if size else image.size
        )

    except Exception as e:
        print(f"Error loading SVG {svg_path}: {e}")
        return None
