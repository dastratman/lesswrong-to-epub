import argparse
import requests
from bs4 import BeautifulSoup
from ebooklib import epub
import time
import os
import re
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
import lxml.html
import lxml.etree
import html  # For html.escape
import random
import mimetypes
import shutil
import datetime

# --- Configuration ---
BASE_URL = "https://www.lesswrong.com"
USER_AGENT = "LessWrongEbookDownloader/1.0"
# seconds between requests to be polite (reduced for faster testing, increase if issues)
REQUEST_DELAY = 0.5
IMAGES_DIR = "epub_images"  # Directory to store downloaded images

# --- Helper Functions ---


def make_soup(url):
    """Fetches a URL and returns a BeautifulSoup object using html5lib parser."""
    print(f"Fetching: {url}")
    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
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


def download_image(image_url, images_dir=IMAGES_DIR):
    """Download an image and return its local filename."""
    if not os.path.exists(images_dir):
        os.makedirs(images_dir)

    # Extract the filename from the URL and sanitize it
    parsed_url = urlparse(image_url)
    image_name = sanitize_filename(os.path.basename(parsed_url.path))

    # If no valid filename, generate one
    if not image_name or image_name == '_':
        # Generate a unique filename based on the URL hash
        image_name = f"image_{hash(image_url) % 10000}_{int(time.time())}_{random.randint(1000, 9999)}"

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

    local_path = os.path.join(images_dir, image_name)

    # If the file was already downloaded, just return the name
    if os.path.exists(local_path):
        return image_name

    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(
            image_url, headers=headers, stream=True, timeout=30)
        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"Downloaded image: {image_name}")
            return image_name
        else:
            print(
                f"Failed to download image {image_url}: HTTP {response.status_code}")
    except Exception as e:
        print(f"Error downloading image {image_url}: {e}")

    return None


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


def get_post_content(post_url):
    """
    Fetches a single post and extracts its title, author, date, and content.
    Returns a dictionary with all post details or None.
    """
    if not post_url.startswith('http'):
        post_url = urljoin(BASE_URL, post_url)

    soup = make_soup(post_url)
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
                else:
                    # If download failed, add a placeholder
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

    return {
        'title': title_text,
        'content': cleaned_content,
        'url': post_url,
        'author': author,
        'date': date_str
    }


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


def get_urls_from_sequence(sequence_url):
    if not sequence_url.startswith('http'):
        sequence_url = urljoin(BASE_URL, sequence_url)

    print(f"Fetching sequence: {sequence_url}")
    soup = make_soup(sequence_url)
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
            # else:
            #     print(f"Skipping non-post link from sequence: {full_url}")

    if not post_urls:
        print(
            f"No post URLs found on sequence page: {sequence_url} after trying all selectors.")
    else:
        print(f"Found {len(post_urls)} posts in sequence.")
    return post_urls


def get_urls_from_bestof(year="all", category="all"):
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

    print(f"Fetching Best Of LessWrong: {bestof_url}")
    soup = make_soup(bestof_url)
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
    return post_urls


def get_urls_from_sequence_list(list_url):
    """
    Fetches a page containing links to multiple sequences and returns
    all post URLs from all sequences found.
    """
    if not list_url.startswith('http'):
        list_url = urljoin(BASE_URL, list_url)

    print(f"Fetching sequence list: {list_url}")
    soup = make_soup(list_url)
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
        posts_in_sequence = get_urls_from_sequence(sequence_url)
        all_post_urls.extend(posts_in_sequence)

    # Deduplicate post URLs
    all_post_urls = list(dict.fromkeys(all_post_urls))
    print(f"\nTotal unique posts from all sequences: {len(all_post_urls)}")
    return all_post_urls


def create_epub(posts_data, epub_filename="lesswrong_ebook.epub", book_title="LessWrong Collection", book_author="LessWrong Community"):
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

    # Add images to the EPUB
    if os.path.exists(IMAGES_DIR):
        print(f"Adding images to EPUB...")
        for img_file in os.listdir(IMAGES_DIR):
            img_path = os.path.join(IMAGES_DIR, img_file)
            if os.path.isfile(img_path):
                # Determine media type
                media_type = mimetypes.guess_type(img_path)[0]
                if not media_type:
                    # Default to JPEG if unknown
                    media_type = 'image/jpeg'
                    if img_file.lower().endswith('.png'):
                        media_type = 'image/png'
                    elif img_file.lower().endswith('.gif'):
                        media_type = 'image/gif'
                    elif img_file.lower().endswith('.svg'):
                        media_type = 'image/svg+xml'

                # Add image to book
                with open(img_path, 'rb') as f:
                    img_content = f.read()

                img_item = epub.EpubItem(
                    uid=f"image_{sanitize_filename(img_file)}",
                    file_name=f"images/{img_file}",
                    media_type=media_type,
                    content=img_content
                )
                book.add_item(img_item)

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

        chapter_body_content_from_post = str(
            chapter_body_content_from_post)  # Ensure string

        # Make sure chapter filename is safe for the filesystem
        chapter_filename = f"chap_{i+1:03d}_{sanitize_filename(chapter_title)}.xhtml"

        # Create the chapter
        chapter = epub.EpubHtml(title=chapter_title,
                                file_name=chapter_filename)
        chapter.content = chapter_body_content_from_post

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
'''
    default_css = epub.EpubItem(
        uid="style_default", file_name="style.css", media_type="text/css", content=style_content)
    book.add_item(default_css)

    book.toc = tuple(toc_links)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters

    print("Attempting to write EPUB...")
    try:
        epub.write_epub(epub_filename, book, {})
        print(f"EPUB created: {epub_filename}")
    except lxml.etree.ParserError as e_write_lxml:
        print(
            f"\nCRITICAL LXML PARSING ERROR DURING EPUB WRITE for: {epub_filename}")
        print(f"Error message: {e_write_lxml}")
        print("This means EbookLib's internal parsing (for nav/toc) failed on a chapter's body content.")
        print("Check any DEBUG messages above if get_body_content() was reported empty for a chapter.")
    except Exception as e_write_generic:
        print(f"\nUNEXPECTED ERROR DURING EPUB WRITE for: {epub_filename}")
        print(
            f"Error type: {type(e_write_generic).__name__}, Message: {e_write_generic}")


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

    parser.add_argument('--year', default="all",
                        help="Year for 'Best of' (e.g., 2023, all).")
    parser.add_argument('--category', default="all", help="Category for 'Best of' (e.g., 'AI Strategy', all). "
                        "Valid: Rationality, World, Optimization, AI Strategy, Technical AI Safety, Practical, All.")

    args = parser.parse_args()
    all_post_urls = []

    # Create images directory if it doesn't exist
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)
    else:
        # Clean up old images to prevent accumulation
        shutil.rmtree(IMAGES_DIR)
        os.makedirs(IMAGES_DIR)

    if args.file:
        all_post_urls = get_urls_from_file(args.file)
    elif args.sequence:
        all_post_urls = get_urls_from_sequence(args.sequence)
    elif args.sequence_list:
        all_post_urls = get_urls_from_sequence_list(args.sequence_list)
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
            year_arg_lower, category_to_use if category_arg_lower != "all" else "all")

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

        post_data = get_post_content(url_to_process)
        if post_data:
            posts_data.append(post_data)
            processed_urls_during_fetch.add(url_to_process)
        else:
            print(f"Failed to retrieve or parse post: {url_to_process}")

    if posts_data:
        create_epub(posts_data, args.output, args.title, args.author)
    else:
        print("No post content successfully retrieved. EPUB not created.")

    # Clean up images directory if desired
    # Uncomment if you want to delete images after EPUB creation
    # if os.path.exists(IMAGES_DIR):
    #     shutil.rmtree(IMAGES_DIR)
