import argparse
import requests
from bs4 import BeautifulSoup
from ebooklib import epub
import time
import os
import re
import json
import hashlib
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
import lxml.html
import lxml.etree
import html  # For html.escape
import random
import mimetypes
import shutil
import datetime
import base64
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import subprocess

# --- Configuration ---
BASE_URL = "https://www.lesswrong.com"
USER_AGENT = "LessWrongEbookDownloader/1.0"
# seconds between requests to be polite (reduced for faster testing, increase if issues)
REQUEST_DELAY = 0.5
IMAGES_DIR = "epub_images"  # Directory to store downloaded images
CACHE_DIR = "lw_cache"  # Main cache directory
PAGE_CACHE_DIR = os.path.join(CACHE_DIR, "pages")  # Cached HTML pages
POST_CACHE_DIR = os.path.join(CACHE_DIR, "posts")  # Cached post data
SEQUENCE_CACHE_DIR = os.path.join(
    CACHE_DIR, "sequences")  # Cached sequence data
MAX_RETRIES = 3  # Number of times to retry downloading an image
RETRY_DELAY = 2  # Seconds to wait between retries
CACHE_EXPIRY_DAYS = 30  # Default cache expiry (in days)

# --- Helper Functions ---


def setup_cache_dirs():
    """Create cache directory structure if it doesn't exist."""
    for directory in [CACHE_DIR, PAGE_CACHE_DIR, POST_CACHE_DIR, SEQUENCE_CACHE_DIR, IMAGES_DIR]:
        if not os.path.exists(directory):
            os.makedirs(directory)


def url_to_cache_key(url):
    """Convert a URL to a cache key."""
    # Use hash for a shorter filename while keeping uniqueness
    hashed = hashlib.md5(url.encode('utf-8')).hexdigest()
    return hashed


def cache_page(url, content):
    """Cache the content for a URL."""
    cache_key = url_to_cache_key(url)
    cache_path = os.path.join(PAGE_CACHE_DIR, f"{cache_key}.html")

    # Convert bytes to base64 string for JSON serialization
    if isinstance(content, bytes):
        content_str = base64.b64encode(content).decode('ascii')
        is_binary = True
    else:
        content_str = content
        is_binary = False

    # Store the page content along with a timestamp and original URL
    cache_data = {
        'url': url,
        'timestamp': time.time(),
        'content': content_str,
        'is_binary': is_binary  # Flag to indicate if content was binary
    }

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f)


def get_cached_page(url, max_age_days=CACHE_EXPIRY_DAYS):
    """Get cached content for a URL if it exists and isn't too old."""
    cache_key = url_to_cache_key(url)
    cache_path = os.path.join(PAGE_CACHE_DIR, f"{cache_key}.html")

    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # Check if cache is expired
            cache_age = (
                time.time() - cache_data['timestamp']) / (60 * 60 * 24)  # in days
            if max_age_days > 0 and cache_age > max_age_days:
                return None  # Cache is too old

            # Convert back from base64 string to bytes if it was binary
            if cache_data.get('is_binary', False):
                return base64.b64decode(cache_data['content'])
            else:
                return cache_data['content']

        except Exception as e:
            print(f"Error reading cache for {url}: {e}")

    return None


def cache_post_data(post_url, post_data):
    """Cache the extracted post data."""
    cache_key = url_to_cache_key(post_url)
    cache_path = os.path.join(POST_CACHE_DIR, f"{cache_key}.json")

    # Add timestamp for cache expiry checking
    post_data_with_meta = post_data.copy()
    post_data_with_meta['_cache_timestamp'] = time.time()

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(post_data_with_meta, f, ensure_ascii=False, indent=2)


def get_cached_post_data(post_url, max_age_days=CACHE_EXPIRY_DAYS):
    """Get cached post data if it exists and isn't too old."""
    cache_key = url_to_cache_key(post_url)
    cache_path = os.path.join(POST_CACHE_DIR, f"{cache_key}.json")

    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                post_data = json.load(f)

            # Check if cache is expired
            if '_cache_timestamp' in post_data:
                cache_age = (
                    time.time() - post_data['_cache_timestamp']) / (60 * 60 * 24)  # in days
                if max_age_days > 0 and cache_age > max_age_days:
                    return None  # Cache is too old

                # Remove cache metadata before returning
                if '_cache_timestamp' in post_data:
                    del post_data['_cache_timestamp']

                return post_data
        except Exception as e:
            print(f"Error reading post cache for {post_url}: {e}")

    return None


def cache_sequence_urls(sequence_url, post_urls):
    """Cache the URLs extracted from a sequence."""
    cache_key = url_to_cache_key(sequence_url)
    cache_path = os.path.join(SEQUENCE_CACHE_DIR, f"{cache_key}.json")

    sequence_data = {
        'url': sequence_url,
        'timestamp': time.time(),
        'post_urls': post_urls
    }

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(sequence_data, f, ensure_ascii=False, indent=2)


def get_cached_sequence_urls(sequence_url, max_age_days=CACHE_EXPIRY_DAYS):
    """Get cached sequence URLs if they exist and aren't too old."""
    cache_key = url_to_cache_key(sequence_url)
    cache_path = os.path.join(SEQUENCE_CACHE_DIR, f"{cache_key}.json")

    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                sequence_data = json.load(f)

            # Check if cache is expired
            cache_age = (
                time.time() - sequence_data['timestamp']) / (60 * 60 * 24)  # in days
            if max_age_days > 0 and cache_age > max_age_days:
                return None  # Cache is too old

            return sequence_data['post_urls']
        except Exception as e:
            print(f"Error reading sequence cache for {sequence_url}: {e}")

    return None


def make_soup(url, use_cache=True, max_cache_age=CACHE_EXPIRY_DAYS):
    """Fetches a URL and returns a BeautifulSoup object using html5lib parser with caching."""
    print(f"Processing URL: {url}")

    # Check cache first if enabled
    if use_cache:
        cached_content = get_cached_page(url, max_cache_age)
        if cached_content:
            print(f"Using cached version of: {url}")
            # Make sure we're passing bytes to BeautifulSoup
            if not isinstance(cached_content, bytes):
                cached_content = cached_content.encode('utf-8')
            return BeautifulSoup(cached_content, 'html5lib')

    print(f"Fetching: {url}")
    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        # Cache the page content
        if use_cache:
            cache_page(url, response.content)

        time.sleep(REQUEST_DELAY)
        return BeautifulSoup(response.content, 'html5lib')
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None


def sanitize_filename(name):
    """Sanitizes a string to be a valid filename."""
    if not name:
        return f"unnamed_{int(time.time())}"
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'_+', '_', name)  # Consolidate multiple underscores
    return name[:100]


def clean_html_for_epub(html_content):
    """Clean HTML content to ensure it's valid for EPUB."""
    if not html_content:
        return ""

    # First, try parsing with html5lib which is more forgiving
    try:
        soup = BeautifulSoup(html_content, 'html5lib')

        # Fix SVG tags which might cause issues
        for svg in soup.find_all('svg'):
            # Either properly namespace SVG or replace with an img if reference exists
            if svg.get('src'):
                img = soup.new_tag('img')
                img['src'] = svg['src']
                img['alt'] = svg.get('alt', 'SVG Image')
                svg.replace_with(img)

        # Remove problematic elements and attributes
        for script in soup.find_all(['script', 'style', 'iframe']):
            script.decompose()

        # Remove on* attributes (event handlers)
        for tag in soup.find_all(True):
            attrs_to_remove = [
                attr for attr in tag.attrs if attr.startswith('on')]
            for attr in attrs_to_remove:
                del tag[attr]

        # Return the cleaned HTML
        return str(soup)

    except Exception as e:
        print(f"Error during HTML cleaning with html5lib: {e}")

        # Fall back to more aggressive cleaning
        try:
            # Try lxml as a fallback
            doc = lxml.html.fromstring(html_content)
            # Convert back to string, which can help normalize HTML
            clean_html = lxml.html.tostring(doc, encoding='unicode')
            return clean_html
        except Exception as e2:
            print(f"Error during fallback HTML cleaning: {e2}")

            # Last resort: basic entity escaping
            return f"<p>Content could not be properly formatted. Error: {html.escape(str(e))}</p>"


def clean_html_for_kindle_compatibility(html_content):
    """Clean HTML to ensure it's compatible with Kindle devices."""
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, 'html.parser')

    # Fix img tags - ensure they have proper attributes
    for img in soup.find_all('img'):
        # Remove empty src attributes
        if not img.get('src'):
            img['src'] = "#"

        # Ensure alt text exists
        if not img.get('alt'):
            img['alt'] = "Image"

        # Remove problematic attributes that Kindle doesn't like
        for attr in ['loading', 'srcset', 'data-src', 'data-srcset', 'width', 'height']:
            if attr in img.attrs:
                del img[attr]

        # Ensure src doesn't have spaces
        if img.get('src'):
            img['src'] = img['src'].replace(' ', '%20')

    # Remove potentially problematic elements for Kindle
    for elem in soup.select('svg, canvas, video, audio, iframe, script, style'):
        elem.decompose()

    # Fix non-standard HTML that might cause issues
    for tag in soup.find_all():
        # Remove on* event attributes
        for attr in list(tag.attrs.keys()):
            if attr.startswith('on'):
                del tag[attr]

    return str(soup)


def get_image_mimetype(image_url):
    """Determine the mimetype of an image based on its URL or extension."""
    # First, try to use the file extension
    ext = os.path.splitext(urlparse(image_url).path)[1].lower()
    if ext:
        guessed_type = mimetypes.guess_type(ext)[0]
        if guessed_type:
            return guessed_type

    # Common image extensions to MIME types mapping
    mime_map = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.webp': 'image/webp'
    }

    # Check if the extension is in our mapping
    if ext in mime_map:
        return mime_map[ext]

    # Default to JPEG if we can't determine the type
    return 'image/jpeg'


def create_placeholder_image(text="Image could not be loaded", width=400, height=200):
    """Create a simple placeholder image with error text."""
    # Create an image with a light gray background
    img = Image.new('RGB', (width, height), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)

    # Add a border
    draw.rectangle([(0, 0), (width-1, height-1)],
                   outline=(200, 200, 200), width=2)

    # Add error text
    try:
        # Try to use a system font if available
        # If no font can be loaded, this will gracefully fall back to default
        try:
            font = ImageFont.truetype("Arial", 20)
        except IOError:
            try:
                font = ImageFont.truetype("DejaVuSans", 20)
            except IOError:
                font = ImageFont.load_default()
    except Exception:
        # Final fallback if something goes wrong with font loading
        font = None

    # Calculate text position to center it
    text_lines = text.split('\n')
    line_height = 25  # Approximate line height
    start_y = (height - (len(text_lines) * line_height)) // 2

    # Draw each line of text
    for i, line in enumerate(text_lines):
        # Check if we need to use textlength or textbbox depending on Pillow version
        try:
            text_width = draw.textlength(line, font=font)
        except AttributeError:
            # Fall back to older method or approximate method for older Pillow versions
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
            except AttributeError:
                # Rough approximation if no method is available
                text_width = len(line) * 10  # Rough estimate of text width

        text_position = ((width - text_width) // 2, start_y + i * line_height)
        draw.text(text_position, line, fill=(80, 80, 80), font=font)

    # Save as a BytesIO object
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    return img_bytes.getvalue()


def validate_image(img_path):
    """
    Validates if a file is a proper image before trying to optimize it.
    Returns True if valid, False otherwise.
    """
    try:
        # Try to open the image with PIL to verify it's valid
        with Image.open(img_path) as img:
            # Force image load to verify data integrity
            img.verify()
        return True
    except Exception:
        # Try a second verification method if the first fails
        try:
            with Image.open(img_path) as img:
                # Try to load image data - this can sometimes work when verify() fails
                img.load()
            return True
        except Exception as e:
            print(f"Invalid image file {os.path.basename(img_path)}: {e}")
            return False


def download_image(image_url, images_dir=IMAGES_DIR):
    """Download an image with retry logic and return its local filename."""
    # Skip data URLs and problematic URLs
    if image_url.startswith('data:'):
        return None

    # Skip URLs that typically fail or aren't needed
    if any(domain in image_url for domain in [
        'amazon-adsystem.com',
        'googleadservices.com',
        'doubleclick.net',
        'analytics.com',
    ]):
        print(f"Skipping known problematic URL: {image_url}")
        return create_error_image_entry(image_url, "Skipped ad/tracking image URL")

    if not os.path.exists(images_dir):
        os.makedirs(images_dir)

    # Extract the filename from the URL and sanitize it
    parsed_url = urlparse(image_url)
    image_name = sanitize_filename(os.path.basename(parsed_url.path))

    # If no valid filename, generate one
    if not image_name or image_name == '_':
        # Generate a unique filename based on the URL hash
        url_hash = hash(image_url) % 100000
        image_name = f"image_{url_hash}_{int(time.time())}_{random.randint(1000, 9999)}"

        # Try to add an extension based on Content-Type
        mime_type = get_image_mimetype(image_url)
        if mime_type == 'image/jpeg':
            image_name += '.jpg'
        elif mime_type == 'image/png':
            image_name += '.png'
        elif mime_type == 'image/gif':
            image_name += '.gif'
        elif mime_type == 'image/svg+xml':
            image_name += '.svg'
        else:
            image_name += '.jpg'  # Default extension

    # First check if we already have a cached version
    # Use the hash of the URL as part of the filename to ensure uniqueness
    url_hash = url_to_cache_key(image_url)[:12]  # Take first 12 chars of hash
    hashed_image_name = f"{url_hash}_{image_name}"
    local_path = os.path.join(images_dir, hashed_image_name)

    # If the file was already downloaded, just return the name
    if os.path.exists(local_path):
        print(f"Using cached image: {hashed_image_name}")
        return hashed_image_name

    error_message = None

    # Try to download the image with retries
    for attempt in range(MAX_RETRIES):
        try:
            headers = {'User-Agent': USER_AGENT}
            response = requests.get(
                image_url, headers=headers, stream=True, timeout=30)

            if response.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                print(f"Downloaded image: {hashed_image_name}")
                return hashed_image_name
            else:
                error_message = f"HTTP {response.status_code}"
                print(
                    f"Attempt {attempt+1}/{MAX_RETRIES} failed: {error_message}")

        except Exception as e:
            error_message = str(e)
            print(
                f"Error downloading image {image_url} (attempt {attempt+1}/{MAX_RETRIES}): {e}")

        # Wait before retrying
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)

    # If we reached here, all download attempts failed
    return create_error_image_entry(image_url, error_message)


def create_error_image_entry(image_url, error_message):
    """Create a placeholder image for a failed download and return its filename."""
    # Generate a unique name based on the URL
    url_hash = hash(image_url) % 100000
    error_image_name = f"error_image_{url_hash}.png"
    error_image_path = os.path.join(IMAGES_DIR, error_image_name)

    # Only create the placeholder image if it doesn't exist
    if not os.path.exists(error_image_path):
        # Create a placeholder image with error information
        display_url = image_url
        if len(display_url) > 30:
            display_url = display_url[:27] + "..."

        error_text = f"Image could not be loaded\n{display_url}\nError: {error_message}"
        placeholder_img_data = create_placeholder_image(error_text)

        with open(error_image_path, 'wb') as f:
            f.write(placeholder_img_data)

        print(f"Created placeholder for failed image: {error_image_name}")

    return error_image_name


def optimize_image_for_epub(source_path, max_width=800, jpeg_quality=75, png_compression=9, max_size_mb=5.0):
    """
    Creates an optimized copy of an image specifically for EPUB inclusion.
    Returns the optimized image data as bytes or None if image should be excluded.
    """
    try:
        # Check file size before processing
        file_size_mb = os.path.getsize(
            source_path) / (1024 * 1024)  # Convert to MB
        if file_size_mb > max_size_mb:
            print(
                f"Excluding large image ({file_size_mb:.2f} MB): {os.path.basename(source_path)}")
            return None, None

        # Validate the image before processing
        if not validate_image(source_path):
            print(f"Excluding invalid image: {os.path.basename(source_path)}")
            return None, None

        # Get the file extension to determine image type
        file_ext = os.path.splitext(source_path)[1].lower()

        # For SVG files, convert to PNG for Kindle compatibility
        if file_ext == '.svg':
            try:
                # Return the original SVG which won't work on Kindle
                print(
                    f"Warning: SVG files not fully supported on all readers: {os.path.basename(source_path)}")
                with open(source_path, 'rb') as f:
                    return f.read(), 'image/svg+xml'
            except Exception as e:
                print(
                    f"Error processing SVG {os.path.basename(source_path)}: {e}")
                return None, None

        # For GIF files, check if they're too large
        if file_ext == '.gif':
            with open(source_path, 'rb') as f:
                content = f.read()
                if len(content) > max_size_mb * 1024 * 1024:
                    print(
                        f"GIF exceeds size limit: {os.path.basename(source_path)}")
                    return None, None
                return content, 'image/gif'

        # For JPEG, PNG, and WEBP files, optimize
        if file_ext in ['.jpg', '.jpeg', '.png', '.webp']:
            img = Image.open(source_path)

            # Convert RGBA to RGB if needed (for JPEGs)
            if img.mode == 'RGBA' and file_ext in ['.jpg', '.jpeg']:
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])  # Use alpha as mask
                img = background

            # Resize if larger than max_width
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                try:
                    # For Pillow >= 9.1.0
                    img = img.resize((max_width, new_height),
                                     Image.Resampling.LANCZOS)
                except AttributeError:
                    # For older Pillow
                    img = img.resize((max_width, new_height), Image.LANCZOS)

            # Save to bytes IO
            output = BytesIO()

            if file_ext in ['.jpg', '.jpeg']:
                img.save(output, format='JPEG',
                         optimize=True, quality=jpeg_quality)
                mime_type = 'image/jpeg'
            elif file_ext == '.webp':
                # Convert WEBP to JPEG for better compatibility
                img.save(output, format='JPEG',
                         optimize=True, quality=jpeg_quality)
                mime_type = 'image/jpeg'
            elif file_ext == '.png':
                img.save(output, format='PNG', optimize=True,
                         compress_level=png_compression)
                mime_type = 'image/png'

            output.seek(0)
            result = output.getvalue()

            # Check if the optimized image is still too large
            if len(result) > max_size_mb * 1024 * 1024:
                print(
                    f"Optimized image still too large ({len(result)/(1024*1024):.2f} MB): {os.path.basename(source_path)}")
                return None, None

            return result, mime_type

        # For unsupported formats, return original if not too large
        with open(source_path, 'rb') as f:
            content = f.read()
            if len(content) > max_size_mb * 1024 * 1024:
                print(
                    f"Unsupported image format too large: {os.path.basename(source_path)}")
                return None, None
            return content, mimetypes.guess_type(source_path)[0] or 'application/octet-stream'

    except Exception as e:
        print(f"Error optimizing image {os.path.basename(source_path)}: {e}")
        return None, None


def format_date(date_str):
    """Format a date string in a consistent way."""
    if not date_str:
        return "Unknown date"

    try:
        # Parse ISO format date
        dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        # Format as "Month Day, Year"
        return dt.strftime("%B %d, %Y")
    except Exception as e:
        # Return the original if parsing fails
        return date_str


def get_post_content(post_url, use_cache=True, max_cache_age=CACHE_EXPIRY_DAYS):
    """
    Fetches a single post and extracts its title, author, date, and content.
    Returns a dictionary with all post details or None.
    """
    if not post_url.startswith('http'):
        post_url = urljoin(BASE_URL, post_url)

    # Check cache first if enabled
    if use_cache:
        cached_post = get_cached_post_data(post_url, max_cache_age)
        if cached_post:
            print(f"Using cached version of post: {post_url}")
            return cached_post

    soup = make_soup(post_url, use_cache, max_cache_age)
    if not soup:
        return None

    # --- Extract title ---
    title_tag = soup.select_one('h1.PostsPageTitle-root a.PostsPageTitle-link')
    if not title_tag:
        title_tag = soup.select_one('h1.PostsPageTitle-root')
    if not title_tag:
        title_tag = soup.select_one('h1.PostsPageTitle-title')  # Older
    if not title_tag:
        title_tag = soup.select_one(
            'h1.SequencePage-title')  # Sequence direct view

    # --- Extract author ---
    author = "Unknown author"
    author_tag = soup.select_one('.PostsAuthors-authorName a')
    if not author_tag:
        author_tag = soup.select_one('.PostsAuthors-authorName')
    if not author_tag:
        author_tag = soup.select_one(
            '.UsersNameDisplay-userName')  # Try another class

    if author_tag:
        author = author_tag.get_text(strip=True)

    # --- Extract date ---
    date_str = "Unknown date"
    date_tag = soup.select_one('time[datetime]')
    if date_tag and date_tag.has_attr('datetime'):
        date_iso = date_tag.get('datetime')
        date_str = format_date(date_iso)
    else:
        # Try to find a date display element
        date_display = soup.select_one('.PostsPageDate-date')
        if date_display:
            date_str = date_display.get_text(strip=True)

    # --- Extract content ---
    content_div_to_render = soup.select_one('div#postContent')
    if content_div_to_render:  # If #postContent exists, drill down
        inline_wrapper = content_div_to_render.select_one(
            'div.InlineReactSelectionWrapper-root > div')
        if inline_wrapper:
            content_div_to_render = inline_wrapper
    else:  # Fallbacks if #postContent (or its structure) isn't found
        content_div_to_render = soup.select_one(
            'div.PostsPage-postContent div.ContentStyles-base')
        if not content_div_to_render:
            content_div_to_render = soup.select_one('div.content')  # Generic

    # --- Title determination ---
    if not title_tag:
        print(f"Could not find title_tag for {post_url}. Using fallback.")
        title_text = f"Untitled Post ({post_url.split('/')[-1] if post_url else 'Unknown URL'})"
    else:
        # Fix: Properly process title including spans to preserve spaces
        # If title contains nested spans, ensure spaces are preserved
        if title_tag.find_all('span'):
            # Get all text content preserving whitespace between spans
            title_pieces = []
            for item in title_tag.contents:
                if isinstance(item, str):
                    title_pieces.append(item)
                else:  # A tag like span
                    title_pieces.append(item.get_text())
            title_text = ''.join(title_pieces).strip()
        else:
            # Simple case: no spans or other complex structure
            title_text = title_tag.get_text(strip=True)

        if not title_text.strip():
            title_text = f"Untitled Post ({post_url.split('/')[-1] if post_url else 'Unknown URL'})"

    # Clean up any extra spaces in title
    title_text = re.sub(r'\s+', ' ', title_text).strip()
    escaped_title = html.escape(title_text)

    # --- Content rendering ---
    rendered_html_part = ""
    if not content_div_to_render:
        print(f"Could not find content_div_to_render for {post_url}.")
    else:
        # Clean up common UI elements from the content before stringifying
        selectors_to_remove = [
            'div.commentOnSelection', '.AudioToggle-audioIcon', '.VoteArrowIconSolid-root',
            '.PostActionsButton-root', '.ReviewPillContainer-root', '.LWPostsPageHeader-root',
            'div[class*="reaction-buttons"]', 'div.PostsVoteDefault-voteBlock',
        ]
        for selector in selectors_to_remove:
            for element_to_remove in content_div_to_render.select(selector):
                element_to_remove.decompose()

        # Process and download images
        for img_tag in content_div_to_render.find_all('img'):
            if img_tag.get('src'):
                img_url = urljoin(post_url, img_tag['src'])

                # Download the image
                local_img_name = download_image(img_url)

                if local_img_name:
                    # Update the src to point to the local file
                    img_tag['src'] = f"images/{local_img_name}"

                    # Keep alt text or add a basic one
                    if not img_tag.get('alt'):
                        img_tag['alt'] = "Image from article"
                else:
                    # If download completely failed with no placeholder
                    img_tag['src'] = ""
                    img_tag['alt'] = f"[Image could not be downloaded: {img_url}]"

            # Remove problematic attributes
            for attr in ['loading', 'srcset', 'data-src']:
                if attr in img_tag.attrs:
                    del img_tag[attr]

            # Handle lazy loading patterns
            noscript_parent = img_tag.find_parent('noscript')
            if noscript_parent:
                noscript_parent.replace_with(img_tag)

        # Process SVG elements
        for svg_tag in content_div_to_render.find_all('svg'):
            # Convert SVG to img if possible, or ensure it has proper namespaces
            if svg_tag.get('src'):
                img_url = urljoin(post_url, svg_tag['src'])
                local_svg_name = download_image(img_url)

                # Create a new img tag to replace the svg
                new_img = soup.new_tag('img')
                new_img['src'] = f"images/{local_svg_name}" if local_svg_name else ""
                new_img['alt'] = svg_tag.get('alt', 'SVG Image')
                svg_tag.replace_with(new_img)
            else:
                # Add required namespaces for inline SVG
                svg_tag['xmlns'] = "http://www.w3.org/2000/svg"
                svg_tag['xmlns:xlink'] = "http://www.w3.org/1999/xlink"

        # Make internal links absolute
        for a_tag in content_div_to_render.find_all('a', href=True):
            href = a_tag['href']
            if not href.startswith('http') or href.startswith('/'):
                a_tag['href'] = urljoin(post_url, href)

        # Remove script and style tags
        for s_tag in content_div_to_render.select('script, style, noscript'):
            s_tag.decompose()

        try:
            rendered_html_part = str(content_div_to_render)
        except Exception as e_str:
            print(
                f"Error stringifying content_div_to_render for {post_url}: {e_str}")
            rendered_html_part = "<p>Error: Could not render content due to stringification error.</p>"

    # --- Create the post header with title, author, date and link ---
    post_header = f"""<h1>{escaped_title}</h1>
    <div class="post-metadata">
        <p class="post-author">by {html.escape(author)}</p>
        <p class="post-date">Published: {html.escape(date_str)}</p>
        <p class="post-link">Original: <a href="{html.escape(post_url)}">{html.escape(post_url)}</a></p>
    </div>
    <hr class="post-header-separator" />
    """

    # --- Construct final body content ---
    if not rendered_html_part.strip():
        print(
            f"Warning: Empty or whitespace-only post body extracted for: {title_text} ({post_url})")
        escaped_url = html.escape(post_url if post_url else "#")
        post_body_html = (f"{post_header}"
                          f"<p>[Content not found or empty for this post. "
                          f"Please check the original URL: <a href='{escaped_url}'>{escaped_url}</a>]</p>")
    else:
        post_body_html = f"{post_header}{rendered_html_part}"

    # Ensure 'content' is never None and always a string
    final_content_for_body = post_body_html if post_body_html is not None else f"{post_header}<p>Fallback: Content was None.</p>"

    # Clean HTML to make it valid for EPUB
    cleaned_content = clean_html_for_epub(final_content_for_body)

    # Prepare final post data
    post_data = {
        'title': title_text,
        'content': cleaned_content,
        'url': post_url,
        'author': author,
        'date': date_str
    }

    # Cache the post data for future use
    if use_cache:
        cache_post_data(post_url, post_data)

    return post_data


def get_urls_from_file(filepath):
    urls = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:  # Added encoding
            for line in f:
                url = line.strip()
                if url and not url.startswith('#'):
                    urls.append(url)
        if not urls:
            print(f"No URLs found in {filepath}")
        return urls
    except FileNotFoundError:
        print(f"Error: File not found at {filepath}")
        return []


def get_urls_from_sequence(sequence_url, use_cache=True, max_cache_age=CACHE_EXPIRY_DAYS):
    """Get post URLs from a sequence with caching."""
    if not sequence_url.startswith('http'):
        sequence_url = urljoin(BASE_URL, sequence_url)

    # Check cache first if enabled
    if use_cache:
        cached_urls = get_cached_sequence_urls(sequence_url, max_cache_age)
        if cached_urls:
            print(f"Using cached sequence data for: {sequence_url}")
            print(f"Found {len(cached_urls)} posts in cached sequence.")
            return cached_urls

    print(f"Fetching sequence: {sequence_url}")
    soup = make_soup(sequence_url, use_cache, max_cache_age)
    if not soup:
        return []

    post_urls = []
    selectors_to_try = [
        # Current main
        'div.LWPostsItem-postsItem span.LWPostsItem-title a[href]',
        # Specific variant
        'div.ChaptersItem-posts span.PostsTitle-eaTitleDesktopEllipsis > a[href]',
        'div.SequencesSmallPostLink-title a[href]',  # Older structure 1
        # Older structure 2
        'div.CollectionPageContents-item a.CollectionPageContents-postTitle[href]',
        # Original /codex example
        'div.LargeSequencesItem-right div.SequencesSmallPostLink-title a[href]'
    ]

    link_elements = []
    for i, selector in enumerate(selectors_to_try):
        link_elements = soup.select(selector)
        if link_elements:
            print(f"Found links using selector variant {i+1}: '{selector}'")
            break
        else:
            print(f"Selector variant {i+1} ('{selector}') found 0 links.")

    for link_tag in link_elements:
        href = link_tag.get('href')
        if href:
            full_url = urljoin(BASE_URL, href)
            if ('/posts/' in full_url and '/p/' not in full_url.split('/posts/')[-1]) or \
               ('/s/' in full_url and '/p/' in full_url):
                if full_url not in post_urls:
                    post_urls.append(full_url)

    if not post_urls:
        print(
            f"No post URLs found on sequence page: {sequence_url} after trying all selectors.")
    else:
        print(f"Found {len(post_urls)} posts in sequence.")

    # Cache the results for future use
    if use_cache and post_urls:
        cache_sequence_urls(sequence_url, post_urls)

    return post_urls


def get_urls_from_bestof(year="all", category="all", use_cache=True, max_cache_age=CACHE_EXPIRY_DAYS):
    """
    Fetches posts from the 'Best of LessWrong' page with optional filtering by year and category.
    Always explicitly sets year=all and category=all in the URL instead of omitting them.
    """
    params = {
        'year': year.lower(),
        'category': category.lower() if category.lower() != "all" else "all"
    }

    query_string = urlencode(params)
    bestof_url = f"{BASE_URL}/bestoflesswrong?{query_string}"

    # Create a cache key that includes the filters
    cache_url = bestof_url  # Use the full URL with query parameters as cache key

    # Check cache first if enabled
    if use_cache:
        cached_urls = get_cached_sequence_urls(cache_url, max_cache_age)
        if cached_urls:
            print(f"Using cached Best Of data for: {bestof_url}")
            print(f"Found {len(cached_urls)} posts in cached Best Of page.")
            return cached_urls

    print(f"Fetching Best Of LessWrong: {bestof_url}")
    soup = make_soup(bestof_url, use_cache, max_cache_age)
    if not soup:
        return []

    post_urls = []
    link_elements = soup.select(
        'div.SpotlightItem-title a[href], a.PostsList-itemTitle[href]')

    for link_tag in link_elements:
        href = link_tag.get('href')
        if href:
            full_url = urljoin(BASE_URL, href)
            if ('/p/' in full_url and ('/s/' in full_url or '/posts/' in full_url)) or \
               ('/posts/' in full_url and not any(x in full_url.split('/posts/')[-1] for x in ['#', '?'])):
                if full_url not in post_urls:
                    post_urls.append(full_url)

    if not post_urls:
        print(f"No post URLs found on Best Of page: {bestof_url}")
    else:
        print(f"Found {len(post_urls)} posts from Best Of page.")

    # Cache the results for future use
    if use_cache and post_urls:
        cache_sequence_urls(cache_url, post_urls)

    return post_urls


def get_urls_from_sequence_list(list_url, use_cache=True, max_cache_age=CACHE_EXPIRY_DAYS):
    """
    Fetches a page containing links to multiple sequences and returns
    all post URLs from all sequences found.
    """
    if not list_url.startswith('http'):
        list_url = urljoin(BASE_URL, list_url)

    # Check cache first if enabled
    if use_cache:
        cached_urls = get_cached_sequence_urls(list_url, max_cache_age)
        if cached_urls:
            print(f"Using cached sequence list data for: {list_url}")
            print(f"Found {len(cached_urls)} posts in cached sequence list.")
            return cached_urls

    print(f"Fetching sequence list: {list_url}")
    soup = make_soup(list_url, use_cache, max_cache_age)
    if not soup:
        return []

    # Extract links to individual sequences
    sequence_links = []

    # Try various selectors used on different sequence list pages
    selectors_to_try = [
        'a.LargeSequencesItem-title[href]',
        'div.SequencesPage-grid a.LargeSequencesItem-title[href]',
        'div.AllSequencesPage-content a.LargeSequencesItem-title[href]',
        'div.SequencesGridItem-title a[href]',
        'a.SequencesPageSequencesList-item[href]'
    ]

    for selector in selectors_to_try:
        sequence_link_elements = soup.select(selector)
        if sequence_link_elements:
            print(
                f"Found {len(sequence_link_elements)} sequence links using selector: '{selector}'")
            for link in sequence_link_elements:
                href = link.get('href')
                if href and ('/s/' in href):
                    full_url = urljoin(BASE_URL, href)
                    sequence_links.append(full_url)
            break  # Stop after finding links with the first successful selector

    if not sequence_links:
        print(f"No sequence links found on page: {list_url}")
        return []

    # Deduplicate sequence links
    sequence_links = list(dict.fromkeys(sequence_links))
    print(
        f"Found {len(sequence_links)} unique sequences. Fetching posts from each sequence...")

    # Get posts from each sequence
    all_post_urls = []
    for sequence_url in sequence_links:
        print(f"\n--- Processing sequence: {sequence_url} ---")
        posts_in_sequence = get_urls_from_sequence(
            sequence_url, use_cache, max_cache_age)
        all_post_urls.extend(posts_in_sequence)

    # Deduplicate post URLs
    all_post_urls = list(dict.fromkeys(all_post_urls))
    print(f"\nTotal unique posts from all sequences: {len(all_post_urls)}")

    # Cache the results for future use
    if use_cache and all_post_urls:
        cache_sequence_urls(list_url, all_post_urls)

    return all_post_urls


def create_epub(posts_data, epub_filename="lesswrong_ebook.epub", book_title="LessWrong Collection",
                book_author="LessWrong Community", max_image_width=800, jpeg_quality=75,
                png_compression=9, max_image_size_mb=5.0, kindle_compatible=False):
    if not posts_data:
        print("No posts to add to EPUB. Exiting.")
        return

    book = epub.EpubBook()
    book.set_identifier(
        f"urn:uuid:{sanitize_filename(book_title)}-lw-{int(time.time())}")
    book.set_title(book_title)
    book.set_language('en')
    book.add_author(book_author)

    chapters = []
    toc_links = []

    # Create a placeholder for excluded images
    excluded_image_placeholder = create_placeholder_image(
        text="Image excluded\n(exceeded size limit)", width=400, height=200)
    excluded_img_name = "image_size_exceeded_placeholder.png"
    excluded_img_path = os.path.join(IMAGES_DIR, excluded_img_name)
    with open(excluded_img_path, 'wb') as f:
        f.write(excluded_image_placeholder)

    # Add placeholder to the book
    placeholder_item = epub.EpubItem(
        uid="image_size_exceeded_placeholder",
        file_name=f"images/{excluded_img_name}",
        media_type="image/png",
        content=excluded_image_placeholder
    )
    book.add_item(placeholder_item)

    # Track which images are referenced in the current posts
    referenced_images = set()

    # First pass: find all image references in the HTML content
    for post in posts_data:
        content = post.get('content', '')
        soup = BeautifulSoup(content, 'html.parser')
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src.startswith('images/'):
                img_filename = src.replace('images/', '')
                referenced_images.add(img_filename)

    print(
        f"Found {len(referenced_images)} images referenced in the selected posts")

    # Track which images are added and which are excluded
    added_images = set()
    excluded_images = set()

    # Only add images that are actually referenced in the posts
    if os.path.exists(IMAGES_DIR):
        print(f"Adding referenced images to EPUB...")
        for img_file in referenced_images:
            # Skip the placeholder (it's already added)
            if img_file == excluded_img_name:
                continue

            img_path = os.path.join(IMAGES_DIR, img_file)
            if os.path.isfile(img_path):
                # Use optimized version for EPUB
                img_content, media_type = optimize_image_for_epub(
                    img_path, max_image_width, jpeg_quality, png_compression, max_image_size_mb)

                if img_content is not None and media_type is not None:
                    img_item = epub.EpubItem(
                        uid=f"image_{sanitize_filename(img_file)}",
                        file_name=f"images/{img_file}",
                        media_type=media_type,
                        content=img_content
                    )
                    book.add_item(img_item)
                    added_images.add(img_file)
                else:
                    excluded_images.add(img_file)

    for i, post in enumerate(posts_data):
        chapter_title = post.get('title', f"Untitled Chapter {i+1}")
        if not chapter_title.strip():
            chapter_title = f"Untitled Chapter {i+1} (Original URL: {post.get('url', 'N/A')})"

        # Clean up any extra spaces in the title
        chapter_title = re.sub(r'\s+', ' ', chapter_title).strip()

        chapter_body_content_from_post = post.get('content')
        current_post_url = post.get('url', '')

        if chapter_body_content_from_post is None or not str(chapter_body_content_from_post).strip():
            print(
                f"CRITICAL WARNING in create_epub: chapter_body_content_from_post for '{chapter_title}' is None or empty. Using emergency placeholder.")

            escaped_title = html.escape(chapter_title)
            escaped_url = html.escape(current_post_url)
            author = html.escape(post.get('author', 'Unknown author'))
            date = html.escape(post.get('date', 'Unknown date'))

            chapter_body_content_from_post = f"""
            <h1>{escaped_title}</h1>
            <div class="post-metadata">
                <p class="post-author">by {author}</p>
                <p class="post-date">Published: {date}</p>
                <p class="post-link">Original: <a href="{escaped_url}">{escaped_url}</a></p>
            </div>
            <hr class="post-header-separator" />
            <p>[Content was unexpectedly empty/None at EPUB creation.]</p>
            """

        # First clean HTML for EPUB
        chapter_content = clean_html_for_epub(
            str(chapter_body_content_from_post))

        # Then apply additional Kindle-specific cleaning if requested
        if kindle_compatible:
            chapter_content = clean_html_for_kindle_compatibility(
                chapter_content)
        else:
            chapter_content = chapter_body_content_from_post

        # Update image references in HTML content for excluded images
        soup = BeautifulSoup(chapter_content, 'html.parser')
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src.startswith('images/'):
                img_filename = src.replace('images/', '')
                if img_filename in excluded_images:
                    # Replace with placeholder
                    img['src'] = f"images/{excluded_img_name}"
                    img['alt'] = f"[Image exceeded size limit: {img_filename}]"
                    img['class'] = img.get('class', []) + ['excluded-image']

                # Ensure all image paths use forward slashes for Kindle compatibility
                img['src'] = img['src'].replace('\\', '/')

        # Make sure chapter filename is safe for the filesystem
        chapter_filename = f"chap_{i+1:03d}_{sanitize_filename(chapter_title)}.xhtml"

        # Create the chapter with the updated content
        chapter = epub.EpubHtml(title=chapter_title,
                                file_name=chapter_filename)
        chapter.content = str(soup)

        chapters.append(chapter)
        book.add_item(chapter)
        toc_links.append(epub.Link(chapter_filename,
                         chapter_title, f"chap{i+1}"))

    style_content = '''
@namespace epub "http://www.idpf.org/2007/ops";
body { font-family: Georgia, serif; line-height: 1.6; margin: 20px; text-rendering: optimizeLegibility; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
h1, h2, h3, h4, h5, h6 { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; margin-top: 1.5em; margin-bottom: 0.5em; line-height: 1.3; color: #333; }
h1 { font-size: 2.2em; padding-bottom: 0.3em; }
h2 { font-size: 1.8em; }
p { margin-bottom: 1.2em; text-align: justify; color: #444; }
img { max-width: 100%; height: auto; display: block; margin: 1.5em auto; border: 1px solid #ddd; border-radius: 4px; padding: 4px; }
blockquote { font-style: italic; margin: 1.5em 20px; padding: 10px 15px; border-left: 4px solid #ccc; background-color: #f9f9f9; color: #555; }
ul, ol { margin-left: 20px; padding-left: 20px; margin-bottom: 1.2em; }
li { margin-bottom: 0.5em; }
pre { background-color: #f6f8fa; padding: 16px; overflow: auto; font-size: 85%; line-height: 1.45; border-radius: 3px; border: 1px solid #ddd; white-space: pre-wrap; word-wrap: break-word; }
code { font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace; font-size: 85%; background-color: #f6f8fa; padding: .2em .4em; margin: 0; border-radius: 3px; }
pre code { padding: 0; margin: 0; background-color: transparent; border: none; }
a { color: #0366d6; text-decoration: none; }
a:hover { text-decoration: underline; }
hr { border: 0; height: 1px; background: #ddd; margin: 2em 0; }
small { font-size: 0.85em; color: #777; }
.post-metadata { font-size: 0.9em; color: #555; margin-bottom: 1.5em; background-color: #f8f9fa; padding: 0.8em; border-radius: 4px; }
.post-author { font-weight: bold; margin: 0 0 0.3em 0; }
.post-date, .post-link { margin: 0 0 0.3em 0; }
.post-header-separator { margin: 1.5em 0; }
.failed-image-notice { text-align: center; font-style: italic; color: #888; background-color: #f8f9fa; padding: 10px; border: 1px solid #ddd; border-radius: 4px; margin: 1em 0; }
.excluded-image { border: 1px dashed #cc0000; background-color: #ffeeee; padding: 5px; }
.image-placeholder { display: inline-block; font-style: italic; color: #666; background-color: #f5f5f5; padding: 2px 5px; border-radius: 3px; }
'''
    default_css = epub.EpubItem(
        uid="style_default", file_name="style.css", media_type="text/css", content=style_content)
    book.add_item(default_css)

    book.toc = tuple(toc_links)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters

    # Report statistics
    print(f"\nImages included in EPUB: {len(added_images)}")
    print(
        f"Images excluded due to size or validation errors: {len(excluded_images)}")
    if excluded_images:
        print("Examples of excluded images:")
        for i, img in enumerate(sorted(excluded_images)):
            if i >= 5:  # Show only first 5 examples
                print(f"  ... and {len(excluded_images) - 5} more")
                break
            img_path = os.path.join(IMAGES_DIR, img)
            size_mb = os.path.getsize(img_path) / (1024 * 1024)
            print(f"  - {img} ({size_mb:.2f} MB)")

    print("Attempting to write EPUB...")
    try:
        epub.write_epub(epub_filename, book, {})
        print(f"EPUB created: {epub_filename}")
        return epub_filename  # Return the filename for potential conversion
    except lxml.etree.ParserError as e_write_lxml:
        print(
            f"\nCRITICAL LXML PARSING ERROR DURING EPUB WRITE for: {epub_filename}")
        print(f"Error message: {e_write_lxml}")
        print("This means EbookLib's internal parsing (for nav/toc) failed on a chapter's body content.")
        print("Check any DEBUG messages above if get_body_content() was reported empty for a chapter.")
        return None
    except Exception as e_write_generic:
        print(f"\nUNEXPECTED ERROR DURING EPUB WRITE for: {epub_filename}")
        print(
            f"Error type: {type(e_write_generic).__name__}, Message: {e_write_generic}")
        return None


def convert_to_mobi(epub_path):
    """Attempt to convert EPUB to MOBI using Calibre's ebook-convert if available."""
    if not os.path.exists(epub_path):
        print(f"Error: EPUB file not found at {epub_path}")
        return False

    mobi_path = os.path.splitext(epub_path)[0] + ".mobi"

    try:
        # Check if ebook-convert (from Calibre) is available
        try:
            # On Windows, use 'where' command
            if os.name == 'nt':
                subprocess.run(['where', 'ebook-convert'], check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                # On Unix-like systems, use 'which' command
                subprocess.run(['which', 'ebook-convert'], check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            print(f"Converting {epub_path} to MOBI format...")
            result = subprocess.run(
                ['ebook-convert', epub_path, mobi_path,
                    '--output-profile', 'kindle'],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            print(f"Successfully converted to MOBI: {mobi_path}")
            return True

        except subprocess.CalledProcessError:
            print(
                "Calibre's ebook-convert tool not found. Please install Calibre to enable MOBI conversion.")
            return False

    except Exception as e:
        print(f"Error during MOBI conversion: {e}")
        return False


def clear_cache(cache_type="all"):
    """Clear specified cache or all caches."""
    if cache_type in ["all", "pages"]:
        if os.path.exists(PAGE_CACHE_DIR):
            print(f"Clearing page cache...")
            shutil.rmtree(PAGE_CACHE_DIR)
            os.makedirs(PAGE_CACHE_DIR)

    if cache_type in ["all", "posts"]:
        if os.path.exists(POST_CACHE_DIR):
            print(f"Clearing post cache...")
            shutil.rmtree(POST_CACHE_DIR)
            os.makedirs(POST_CACHE_DIR)

    if cache_type in ["all", "sequences"]:
        if os.path.exists(SEQUENCE_CACHE_DIR):
            print(f"Clearing sequence cache...")
            shutil.rmtree(SEQUENCE_CACHE_DIR)
            os.makedirs(SEQUENCE_CACHE_DIR)

    if cache_type in ["all", "images"]:
        if os.path.exists(IMAGES_DIR):
            print(f"Clearing image cache...")
            shutil.rmtree(IMAGES_DIR)
            os.makedirs(IMAGES_DIR)

    if cache_type == "all":
        print("All caches cleared.")


def split_epub_by_size(posts_data, max_posts_per_file=50, base_filename="lesswrong"):
    """Split posts into multiple EPUBs to keep file sizes manageable."""
    if len(posts_data) <= max_posts_per_file:
        return [{"filename": f"{base_filename}.epub", "posts": posts_data}]

    volumes = []
    for i in range(0, len(posts_data), max_posts_per_file):
        chunk = posts_data[i:i+max_posts_per_file]
        volumes.append({
            "filename": f"{base_filename}_vol{i//max_posts_per_file + 1}.epub",
            "posts": chunk
        })
    return volumes


# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download LessWrong posts and create an EPUB.")
    parser.add_argument(
        '-o', '--output', default="lesswrong_ebook.epub", help="Output EPUB filename.")
    parser.add_argument(
        '--title', default="LessWrong Collection", help="Title of the EPUB book.")
    parser.add_argument('--author', default="LessWrong Community",
                        help="Author of the EPUB book.")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--file', help="Path to a text file containing post URLs.")
    group.add_argument('--sequence', help="URL of a LessWrong sequence.")
    group.add_argument(
        '--sequence-list', help="URL of a page containing multiple sequences (like /codex, /highlights, etc.)")
    group.add_argument('--bestof', action='store_true',
                       help="Download from 'The Best of LessWrong'. Use with --year/--category.")

    # Cache control arguments
    parser.add_argument('--no-cache', action='store_true',
                        help="Don't use cached data, fetch everything fresh.")
    parser.add_argument('--clear-cache', choices=['all', 'pages', 'posts', 'sequences', 'images'],
                        help="Clear specified cache before running.")
    parser.add_argument('--cache-days', type=int, default=CACHE_EXPIRY_DAYS,
                        help=f"Number of days before cache expires (default: {CACHE_EXPIRY_DAYS}, 0 = never expire).")

    parser.add_argument('--year', default="all",
                        help="Year for 'Best of' (e.g., 2023, all).")
    parser.add_argument('--category', default="all", help="Category for 'Best of' (e.g., 'AI Strategy', all). "
                        "Valid: Rationality, World, Optimization, AI Strategy, Technical AI Safety, Practical, All.")

    # Image optimization settings
    parser.add_argument('--max-image-width', type=int, default=800,
                        help="Maximum width for images in the EPUB (default: 800px)")
    parser.add_argument('--jpeg-quality', type=int, default=75,
                        help="JPEG quality (1-100, lower = smaller file, default: 75)")
    parser.add_argument('--png-compression', type=int, default=9,
                        help="PNG compression level (0-9, higher = smaller file, default: 9)")
    parser.add_argument('--max-image-size', type=float, default=5.0,
                        help="Maximum image size in MB. Images larger than this will be excluded (default: 5.0)")
    parser.add_argument('--no-images', action='store_true',
                        help="Exclude all images from the EPUB")

    # Kindle compatibility
    parser.add_argument('--kindle-compatible', action='store_true',
                        help="Apply additional optimizations for Kindle compatibility")
    parser.add_argument('--create-mobi', action='store_true',
                        help="Attempt to convert EPUB to MOBI using Calibre (if installed)")

    # Splitting options
    parser.add_argument('--split', action='store_true',
                        help="Split into multiple volumes for large collections")
    parser.add_argument('--max-posts-per-file', type=int, default=50,
                        help="Maximum number of posts per EPUB file when splitting (default: 50)")
    parser.add_argument('--limit', type=int,
                        help="Limit number of posts to download")

    args = parser.parse_args()
    all_post_urls = []

    # Setup cache directories
    setup_cache_dirs()

    # Handle cache clearing if requested
    if args.clear_cache:
        clear_cache(args.clear_cache)

    # Determine cache settings
    use_cache = not args.no_cache
    cache_days = args.cache_days

    if args.file:
        all_post_urls = get_urls_from_file(args.file)
    elif args.sequence:
        all_post_urls = get_urls_from_sequence(
            args.sequence, use_cache, cache_days)
    elif args.sequence_list:
        all_post_urls = get_urls_from_sequence_list(
            args.sequence_list, use_cache, cache_days)
    elif args.bestof:
        valid_years = [str(y) for y in range(2018, 2025)] + ["all"]
        valid_categories_lower = ["rationality", "world", "optimization", "ai strategy",
                                  "technical ai safety", "practical", "all"]

        year_arg_lower = args.year.lower()
        if year_arg_lower not in valid_years:
            print(f"Invalid year: {args.year}. Valid: {valid_years}.")
            exit(1)

        category_arg_lower = args.category.lower()
        # Ensure we use the properly cased category name if a valid lowercase alias is given
        category_to_use = args.category
        if category_arg_lower != "all":  # "all" doesn't need case matching
            found_cat = False
            for cat_proper_case in ["Rationality", "World", "Optimization", "AI Strategy", "Technical AI Safety", "Practical"]:
                if category_arg_lower == cat_proper_case.lower():
                    category_to_use = cat_proper_case
                    found_cat = True
                    break
            if not found_cat:
                print(
                    f"Invalid category: {args.category}. Valid (case-insensitive): {valid_categories_lower}.")
                exit(1)

        all_post_urls = get_urls_from_bestof(
            year_arg_lower, category_to_use if category_arg_lower != "all" else "all", use_cache, cache_days)

    if not all_post_urls:
        print("No URLs to process. Exiting.")
        exit(1)

    print(
        f"\nCollected {len(set(all_post_urls))} unique post URLs. Fetching content...")  # Use set for unique count display
    posts_data = []
    processed_urls = set()  # Use a set for efficient duplicate checking

    # Deduplicate URLs before processing
    unique_urls_ordered = []
    for url in all_post_urls:
        if url not in processed_urls:
            unique_urls_ordered.append(url)
            processed_urls.add(url)

    # Apply limit if specified
    if args.limit and args.limit > 0:
        unique_urls_ordered = unique_urls_ordered[:args.limit]
        print(f"Limiting to first {args.limit} posts as requested.")

    # Reset processed_urls for the fetching loop if needed, or just use unique_urls_ordered
    # For clarity, we'll iterate unique_urls_ordered and re-use processed_urls for actual fetching status
    processed_urls_during_fetch = set()

    for url_to_process in unique_urls_ordered:
        # This check is somewhat redundant now if unique_urls_ordered is truly unique,
        # but kept for safety / if all_post_urls was not pre-deduplicated.
        if url_to_process in processed_urls_during_fetch:
            # Should not happen with unique_urls_ordered
            print(f"Skipping already processed URL: {url_to_process}")
            continue

        post_data = get_post_content(url_to_process, use_cache, cache_days)
        if post_data:
            posts_data.append(post_data)
            processed_urls_during_fetch.add(url_to_process)
        else:
            print(f"Failed to retrieve or parse post: {url_to_process}")

    if posts_data:
        if args.no_images:
            # Process HTML to remove image references
            for post in posts_data:
                soup = BeautifulSoup(post['content'], 'html.parser')
                for img in soup.find_all('img'):
                    # Replace with alt text in brackets
                    alt_text = img.get('alt', 'Image')
                    replacement = soup.new_tag('span')
                    replacement['class'] = 'image-placeholder'
                    replacement.string = f"[{alt_text}]"
                    img.replace_with(replacement)
                post['content'] = str(soup)
            print("Images have been removed from content as requested.")

        if args.split:
            volumes = split_epub_by_size(posts_data, args.max_posts_per_file,
                                         os.path.splitext(args.output)[0])
            for i, volume in enumerate(volumes):
                vol_title = f"{args.title} - Vol {i+1}" if len(
                    volumes) > 1 else args.title
                print(
                    f"\nCreating volume {i+1} of {len(volumes)}: {volume['filename']}")
                epub_path = create_epub(volume["posts"], volume["filename"], vol_title, args.author,
                                        args.max_image_width, args.jpeg_quality, args.png_compression,
                                        args.max_image_size, args.kindle_compatible)

                if args.create_mobi and epub_path:
                    convert_to_mobi(epub_path)
        else:
            epub_path = create_epub(posts_data, args.output, args.title, args.author,
                                    args.max_image_width, args.jpeg_quality, args.png_compression,
                                    args.max_image_size, args.kindle_compatible)

            if args.create_mobi and epub_path:
                convert_to_mobi(epub_path)
    else:
        print("No post content successfully retrieved. EPUB not created.")
