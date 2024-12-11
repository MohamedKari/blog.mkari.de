from pathlib import Path

def list_image_files():
    image_files = []
    for ext in ('*.PNG', '*.JPG', '*.JPEG', '*.png', '*.jpg', '*.jpeg'):
        for file in Path('.').rglob(ext):
            if not any(excluded in str(file) for excluded in ['.archive', 'compressed']):
                image_files.append(file)
                print(ext, file)
        
    return image_files

def main():
    # Get list of image files
    image_files = list_image_files()
    
    # Process each image
    from PIL import Image
    for img_path in image_files:
        # Create compressed folder next to .raw directory
        compressed_dir = img_path.parent.parent / 'compressed'
        compressed_dir.mkdir(parents=True, exist_ok=True)
        
        # Open image and get EXIF data
        img = Image.open(img_path)
        
        # Check for EXIF orientation and rotate if needed
        try:
            exif = img._getexif()
            if exif:
                orientation = exif.get(274)  # 274 is the orientation tag
                if orientation == 3:
                    img = img.rotate(180, expand=True)
                elif orientation == 6:
                    img = img.rotate(270, expand=True)
                elif orientation == 8:
                    img = img.rotate(90, expand=True)
        except (AttributeError, KeyError, TypeError, ValueError):
            # No EXIF data or orientation info, proceed with original image
            pass
            
        # Calculate new dimensions maintaining aspect ratio
        width, height = img.size
        max_size = 1024
        if width > height:
            new_width = min(width, max_size)
            new_height = int(height * (new_width / width))
        else:
            new_height = min(height, max_size)
            new_width = int(width * (new_height / height))
            
        # Resize and save compressed jpg
        img = img.resize((new_width, new_height))
        output_path = compressed_dir / f"{img_path.stem}.jpg"
        img.save(output_path, "JPEG", quality=95)
        print(output_path)

if __name__ == "__main__":
    main()