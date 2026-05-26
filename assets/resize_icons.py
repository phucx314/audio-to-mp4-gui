import os
from PIL import Image

def resize_all_icons(folder_path, target_size=(64, 64)):
    if not os.path.isdir(folder_path):
        print(f"Directory not found: {folder_path}")
        return

    count = 0
    for filename in os.listdir(folder_path):
        if filename.lower().endswith('.png'):
            file_path = os.path.join(folder_path, filename)
            try:
                # Open the image
                with Image.open(file_path) as img:
                    # Check if it needs resizing
                    if img.size != target_size:
                        # Convert to RGBA just in case
                        img = img.convert("RGBA")
                        # Resize using high-quality downsampling
                        resized_img = img.resize(target_size, Image.Resampling.LANCZOS)
                        # Save it back (overwrite)
                        resized_img.save(file_path, optimize=True)
                        count += 1
                        print(f"Resized: {filename}")
            except Exception as e:
                print(f"Failed to process {filename}: {e}")

    print(f"Done! Resized {count} icons.")

if __name__ == "__main__":
    # Resize built-in icons
    icons_dir = os.path.join(os.path.dirname(__file__), 'icons')
    print("Resizing built-in icons...")
    resize_all_icons(icons_dir)
    
    # Resize user icons if any
    user_icons_dir = os.path.join(os.path.dirname(__file__), 'user_icons')
    if os.path.isdir(user_icons_dir):
        print("\nResizing user icons...")
        resize_all_icons(user_icons_dir)
