:::thinking
Let's create a comprehensive README.md for this LessWrong EPUB downloader script. I'll structure the README with the following sections:

1. Title and brief description
2. Overview and features
3. Requirements
4. Installation
5. Usage
   - Basic usage
   - Command-line options
   - Examples
6. Cache System
7. Image Handling
8. Advanced Options
9. Troubleshooting
10. License

Based on examining the code, this script:
- Downloads posts from LessWrong and converts them to EPUB format
- Supports downloading from:
  - Lists of URLs in a file
  - Sequence pages
  - Sequence list pages
  - The "Best of LessWrong" pages
- Handles caching of pages, posts, sequences, and images
- Optimizes images for inclusion in the EPUB
- Handles HTML cleaning and preparation for EPUB format
- Optionally converts to MOBI format if Calibre is installed
- Supports splitting large collections into multiple volumes
- Has options for Kindle compatibility

Let me now create the README.md file with these details.
:::
# LessWrong EPUB Downloader

A Python script to download posts from [LessWrong](https://www.lesswrong.com) and convert them into EPUB ebooks for offline reading.

## Overview

This tool allows you to easily create ebooks from LessWrong content, including:
- Individual posts
- Complete sequences
- Collections of sequences (like the Codex)
- "Best of LessWrong" compilations

## Features

- Download posts and convert them to EPUB format
- Cache downloaded content to reduce server load and speed up repeat usage
- Extract and optimize images for inclusion in the ebook
- Support for Kindle-compatible formatting
- Convert to MOBI format (requires Calibre)
- Split large collections into multiple volumes
- Control cache expiration and image optimization parameters

## Requirements

- Python 3.6+
- Required Python packages (install via `pip install -r requirements.txt`):
  - requests
  - beautifulsoup4
  - html5lib
  - lxml
  - EbookLib
  - Pillow

## Installation

1. Clone this repository or download the script
2. Install the required dependencies:

```bash
pip install requests beautifulsoup4 html5lib lxml EbookLib Pillow
```

3. (Optional) Install [Calibre](https://calibre-ebook.com/) if you want MOBI conversion capability

## Usage

### Basic Usage

```bash
python lw_downloader.py --sequence "https://www.lesswrong.com/s/pC6DYFLPuxEH8uFSg" --output "book_of_baby_eating_aliens.epub"
```

### Command-line Options

```
required arguments (one of the following):
  --file FILE           Path to a text file containing post URLs
  --sequence SEQUENCE   URL of a LessWrong sequence
  --sequence-list SEQUENCE_LIST
                        URL of a page containing multiple sequences
  --bestof              Download from 'The Best of LessWrong'

output options:
  -o OUTPUT, --output OUTPUT
                        Output EPUB filename (default: lesswrong_ebook.epub)
  --title TITLE         Title of the EPUB book (default: LessWrong Collection)
  --author AUTHOR       Author of the EPUB book (default: LessWrong Community)

cache options:
  --no-cache            Don't use cached data, fetch everything fresh
  --clear-cache {all,pages,posts,sequences,images}
                        Clear specified cache before running
  --cache-days CACHE_DAYS
                        Number of days before cache expires (default: 30, 0 = never expire)

bestof options:
  --year YEAR           Year for 'Best of' (e.g., 2023, all)
  --category CATEGORY   Category for 'Best of' (e.g., 'AI Strategy', all)

image options:
  --max-image-width MAX_IMAGE_WIDTH
                        Maximum width for images in the EPUB (default: 800px)
  --jpeg-quality JPEG_QUALITY
                        JPEG quality (1-100, lower = smaller file, default: 75)
  --png-compression PNG_COMPRESSION
                        PNG compression level (0-9, higher = smaller file, default: 9)
  --max-image-size MAX_IMAGE_SIZE
                        Maximum image size in MB (default: 5.0)
  --no-images           Exclude all images from the EPUB

format options:
  --kindle-compatible   Apply optimizations for Kindle compatibility
  --create-mobi         Convert EPUB to MOBI using Calibre (if installed)

splitting options:
  --split               Split into multiple volumes for large collections
  --max-posts-per-file MAX_POSTS_PER_FILE
                        Maximum posts per EPUB file when splitting (default: 50)
  --limit LIMIT         Limit number of posts to download
```

### Examples

**Download a specific sequence:**
```bash
python lw_downloader.py --sequence "https://www.lesswrong.com/s/HXkpm9b8o964jbQ89" --output "rationality_from_ai_to_zombies.epub"
```

**Download from a text file containing URLs:**
```bash
python lw_downloader.py --file "my_favorite_posts.txt" --title "My Favorite LessWrong Posts" --author "Selected by Me"
```

**Download the 'Codex' (a collection of sequences):**
```bash
python lw_downloader.py --sequence-list "https://www.lesswrong.com/codex" --output "lesswrong_codex.epub"
```

**Download Best of LessWrong for a specific year and category:**
```bash
python lw_downloader.py --bestof --year 2022 --category "AI Strategy" --output "best_of_lw_ai_2022.epub"
```

**Create a Kindle-optimized ebook and convert to MOBI:**
```bash
python lw_downloader.py --sequence "https://www.lesswrong.com/s/dLbkrPjpRatuEEmPm" --kindle-compatible --create-mobi
```

**Split a large collection into multiple volumes:**
```bash
python lw_downloader.py --sequence-list "https://www.lesswrong.com/highlights" --split --max-posts-per-file 30
```

## Cache System

The script caches downloaded content to reduce server load and speed up future runs:

- Pages cache: Stores HTML content of downloaded URLs
- Posts cache: Stores the extracted post data
- Sequences cache: Stores lists of URLs from sequences
- Images cache: Stores downloaded images

The default cache expiry is 30 days. You can:
- Disable caching with `--no-cache`
- Set custom expiry with `--cache-days` (use 0 for no expiry)

## Image Handling

The script downloads and optimizes images for inclusion in the EPUB:
- Large images are resized to fit within the specified maximum width
- Images are optimized to reduce file size
- Images exceeding the maximum size are replaced with a placeholder
- SVG images are maintained but may not display on all readers

## Troubleshooting

**Script errors during execution:**
- Check if the URL structure has changed on LessWrong

**EPUB creation fails:**
- Try with `--no-images` to exclude images
- Check if you have write permissions in the current directory

**MOBI conversion fails:**
- Ensure Calibre is installed and `ebook-convert` is in your PATH
- Try with `--kindle-compatible` flag

**EPUB not displaying correctly on device:**
- Try with `--kindle-compatible` if using on Kindle
- Check if your e-reader supports EPUB format (Kindles may require MOBI)

## License

This script is provided as-is for educational and personal use.

---

*Note: This tool is not officially affiliated with LessWrong. Please use responsibly and consider the load on LessWrong's servers.*