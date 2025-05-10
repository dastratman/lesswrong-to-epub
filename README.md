:::thinking
Let me analyze what's changed in the script from the original README and what needs to be updated:

1. Added functionality for sequence lists: We added the ability to handle URLs that link to lists of sequences (like /codex, /highlights, etc.)

2. Fixed "Best Of" URL encoding: Corrected the URL encoding for spaces in category names

3. Fixed title space handling: Improved handling of spaces in post titles to avoid issues like "slipperyslopes"

4. Fixed EPUB generation: Modified how content is passed to the EbookLib to avoid empty content issues

Based on these changes, I need to:

1. Add documentation for the new `--sequence-list` option
2. Mention the fix for "Best Of" URL encoding (probably not necessary for users)
3. Update any other relevant information

I should also ensure the README accurately reflects the script's current functionality, limitations, and usage.
:::
# LessWrong to EPUB Downloader

A Python script to download posts from [LessWrong.com](https://www.lesswrong.com/) and compile them into an EPUB eBook. Each post becomes a chapter in the generated eBook, making it easy to read your favorite LessWrong content offline on e-readers or other devices.

## Features

*   **Multiple Input Methods:**
    *   Provide a list of specific post URLs via a text file.
    *   Download all posts from a LessWrong Sequence URL.
    *   Download all posts from multiple sequences using a sequence list URL (like /codex or /highlights).
    *   Fetch posts from "The Best of LessWrong" page, with filters for year and/or category.
*   **EPUB Generation:** Creates a well-structured EPUB file with:
    *   One chapter per post.
    *   Post titles as chapter titles.
    *   Basic HTML content cleaning.
    *   Embedded CSS for readability.
    *   Table of Contents.
*   **Customization:**
    *   Specify output EPUB filename.
    *   Set custom book title and author metadata.
*   **Polite Scraping:** Includes a configurable delay between requests to respect LessWrong's servers.

## Prerequisites

*   Python 3.7+
*   `pip` (Python package installer)

## Installation

1.  **Clone the repository (or download the script):**
    ```bash
    git clone https://github.com/dastratman/lesswrong-to-epub.git
    cd lesswrong-to-epub
    ```
    Alternatively, just download the `lw_to_epub.py` script.

2.  **Install required Python libraries:**
    It's recommended to use a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
    Then install the dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## Usage

The script is run from the command line.

```bash
python lw_to_epub.py [MODE] [OPTIONS]
```

**Available Modes (choose one):**

*   `--file FILEPATH`: Path to a text file containing a list of post URLs (one URL per line).
*   `--sequence SEQUENCE_URL`: URL of a LessWrong sequence (e.g., `https://www.lesswrong.com/s/XsMTxdQ6fprAQMoKi`).
*   `--sequence-list LIST_URL`: URL of a page containing multiple sequences (e.g., `/codex`, `/highlights`, `/rationality`).
*   `--bestof`: Download from "The Best of LessWrong" page. Use with `--year` and/or `--category`.

**Options:**

*   `-o OUTPUT_FILENAME`, `--output OUTPUT_FILENAME`: Output EPUB filename (default: `lesswrong_ebook.epub`).
*   `--title BOOK_TITLE`: Title of the EPUB book (default: "LessWrong Collection").
*   `--author BOOK_AUTHOR`: Author of the EPUB book (default: "LessWrong Community").
*   `--year YEAR`: Year for "The Best of LessWrong" (e.g., `2023`, `all`). Default: `all`.
    *   Valid years: `2018`, `2019`, `2020`, `2021`, `2022`, `2023`, `all`.
*   `--category CATEGORY`: Category for "The Best of LessWrong" (e.g., `"AI Strategy"`, `all`). Default: `all`.
    *   Valid categories: `Rationality`, `World`, `Optimization`, `AI Strategy`, `Technical AI Safety`, `Practical`, `All`. (Case-insensitive, use quotes if the category contains spaces).

---

### Examples:

1.  **From a list of URLs in a file (`my_lw_posts.txt`):**
    *   `my_lw_posts.txt`:
        ```
        https://www.lesswrong.com/posts/d9FJHawgkiMSPjagR/ai-control-improving-safety-despite-intentional-subversion
        https://www.lesswrong.com/posts/zthDPAjh9w6Ytbeks/deceptive-alignment
        ```
    *   Command:
        ```bash
        python lw_to_epub.py --file my_lw_posts.txt --output "AI Safety Readings.epub" --title "AI Safety Key Readings"
        ```

2.  **From a Sequence URL:**
    ```bash
    python lw_to_epub.py --sequence https://www.lesswrong.com/s/XsMTxdQ6fprAQMoKi --output "Argument and Analysis.epub" --title "The Argument and Analysis Sequence" --author "Scott Alexander"
    ```

3.  **From a Sequence List URL (e.g., The Codex):**
    ```bash
    python lw_to_epub.py --sequence-list https://www.lesswrong.com/codex --output "The_Codex.epub" --title "The Codex" --author "Scott Alexander"
    ```

4.  **From "The Best of LessWrong":**
    *   All posts from all years and categories:
        ```bash
        python lw_to_epub.py --bestof --output "BestOfLW_AllTime.epub" --title "The Best of LessWrong (All Time)"
        ```
    *   Posts from 2023, all categories:
        ```bash
        python lw_to_epub.py --bestof --year 2023 --output "BestOfLW_2023.epub" --title "Best of LessWrong 2023"
        ```
    *   Posts from all years, "AI Strategy" category:
        ```bash
        python lw_to_epub.py --bestof --category "AI Strategy" --output "BestOfLW_AI_Strategy.epub" --title "Best of LessWrong - AI Strategy"
        ```
    *   Posts from 2022, "Technical AI Safety" category:
        ```bash
        python lw_to_epub.py --bestof --year 2022 --category "Technical AI Safety" --output "BestOfLW_2022_TechAISafety.epub" --title "Best of LessWrong 2022 - Technical AI Safety"
        ```

---

## How It Works

The script uses:
*   `requests` to fetch HTML content from LessWrong.com.
*   `BeautifulSoup4` to parse the HTML and extract post titles and content.
*   `EbookLib` to assemble the extracted content into an EPUB file.

HTML selectors are used to identify relevant parts of the LessWrong pages. These selectors might break if LessWrong significantly changes its website structure.

## Limitations & Future Improvements

*   **Image Handling:** Images are currently linked via their absolute URLs. For full offline viewing, images would need to be downloaded and embedded into the EPUB. Some e-readers might not display remotely hosted images.
*   **Dynamic Content:** The script relies on server-rendered HTML. If LessWrong heavily uses JavaScript to load content, this script might not capture it all without more advanced techniques (e.g., using Selenium).
*   **Complex HTML Structures:** While basic cleanup is done, very complex or unusual HTML within posts might not render perfectly in all e-readers.
*   **Error Robustness:** While some error handling is in place, more specific error catching could be added for edge cases.

## Contributing

Contributions are welcome! If you have suggestions, bug reports, or want to add features:

1.  Fork the repository.
2.  Create a new branch (`git checkout -b feature/your-feature-name`).
3.  Make your changes.
4.  Commit your changes (`git commit -am 'Add some feature'`).
5.  Push to the branch (`git push origin feature/your-feature-name`).
6.  Create a new Pull Request.

Please also feel free to open an issue to discuss potential changes or report problems.

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.