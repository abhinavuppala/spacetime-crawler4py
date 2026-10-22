import re
import logging
from pathlib import Path
import atexit

from urllib.parse import (
    urlparse, urldefrag, urljoin,
    urlsplit, urlunsplit, urlencode,
    quote, parse_qsl
)
from bs4 import BeautifulSoup

from utils import get_logger
from analytics import Analytics
from duplicates import DuplicateDetector


DOMAIN_WHITELIST = (
    "ics.uci.edu",
    "cs.uci.edu",
    "informatics.uci.edu",
    "stat.uci.edu",
)

# file extensions that arent parseable
INVALID_EXTENSIONS = (
    r".*\.(css|js|bmp|gif|jpe?g|ico"
    + r"|png|tiff?|mid|mp2|mp3|mp4"
    + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
    + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
    + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
    + r"|epub|dll|cnf|tgz|sha1"
    + r"|thmx|mso|arff|rtf|jar|csv"
    + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$"
)

# read stopwords from a text file
STOPWORDS = []
stopwords_file = Path('stopwords.txt')
with stopwords_file.open('r') as f:
    STOPWORDS = list(filter(
        lambda word: word,
        map(
            lambda line: line.strip('\n'),
            f.readlines()
        )
    ))
assert len(STOPWORDS) == 174, f"Expected 174 stopwords, got {len(STOPWORDS)}"

# for assignment metrics
analytics = Analytics(STOPWORDS)
duplicates = DuplicateDetector()

# register callback functions to close the shelves on exit
atexit.register(duplicates.close)
atexit.register(analytics.close)

# basic crawl statistics for monitoring
# callback to print them on exit
crawl_stats = {
    "processed": 0,
    "failed": 0,
    "oversized": 0,
    "low_info": 0,
    "duplicates": 0,
    "links_found": 0,
    "links_rejected": 0,
}
atexit.register(
    lambda: print(
        "Crawl Analytics (since crawler start/resume):\n"
        + "\n".join(
            f"{key}: {value}" for key, value in crawl_stats.items()
        )
    )
)

# filter out certain query params
# empty for now until more testing has been done
TRACKING_PARAMS = set()

# guesstimate limits for detecting obvious URL traps
MAX_URL_LENGTH = 2048       # chars
MAX_PATH_DEPTH = 20
MAX_QUERY_PARAMS = 15       
MAX_REPEATED_SEGMENTS = 3   # like /calendar/calendar/calendar/...

# reasonable(?) page content thresholds
MAX_CONTENT_SIZE = 5 * 1024 * 1024


logger = get_logger(f"SCRAPER") # shared logger
logger.setLevel(logging.DEBUG) # DEBUG for development

def scraper(url, resp):
    try:
        links = extract_next_links(url, resp)
        valid_links = [link for link in links if is_valid(link)]

        # log number of links rejected & number of links found
        crawl_stats["links_found"] += len(links)
        crawl_stats["links_rejected"] += (
            len(links) - len(valid_links)
        )

        return valid_links

    except Exception:
        # wrap in a try except to log errors better
        # logger.exception already includes stack trace and logger name has URL
        logger.exception(f"Failed to scrape url {url}")
        crawl_stats["failed"] += 1
        return []

def extract_next_links(url, resp):
    """
    Implementation required.
    url: the URL that was used to get the page
    resp.url: the actual url of the page
    resp.status: the status code returned by the server. 200 is OK, you got the page. Other numbers mean that there was some kind of problem.
    resp.error: when status is not 200, you can check the error here, if needed.
    resp.raw_response: this is where the page actually is. More specifically, the raw_response has two parts:
            resp.raw_response.url: the url, again
            resp.raw_response.content: the content of the page!
    Return a list with the hyperlinks (as strings) scrapped from resp.raw_response.content
    """
    # only parse when code is 200 OK
    # and only if response content exists
    if (
        resp.status != 200
        or resp.raw_response is None
        or not resp.raw_response.content
    ):
        logger.debug(
            f"Skipping content (status={resp.status}): {url}"
        )
        crawl_stats["failed"] += 1
        return []

    base = resp.raw_response.url or url
    # another check for redundancy. cheap since we're network & politeness time-bound
    if not is_valid(base):
        logger.warning(
            f"Invalid URL: {base}"
        )
        crawl_stats["failed"] += 1
        return []

    # avoid processing extremely large HTML responses
    content = resp.raw_response.content
    if len(content) > MAX_CONTENT_SIZE:
        logger.warning(
            f"Oversized page ({len(content)} bytes): {base}"
        )
        crawl_stats["oversized"] += 1
        return []
    
    links = set()

    # look for all <a> tags with hrefs to find outgoing links
    soup = BeautifulSoup(content, "html.parser")
    for a in soup.find_all("a", href=True):
        try:
            # urljoin accounts for absolute or relative links
            abs_link = urljoin(base, a["href"].strip())
            normalized = normalize_url(abs_link)
            if normalized:
                links.add(normalized)
        except ValueError: # skip any malformed links
            continue
    logger.info(f"Found {len(links)} links from {url}.")

    # remove non-text elements
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    # get text for checking identical match
    text = soup.get_text(separator=" ", strip=True)

    normalized = normalize_url(base)

    if normalized:
        # check for identical text across different URLs
        try:
            original_url = duplicates.check_duplicate(
                normalized, text
            )
            # returns None if there's no duplicate. Otherwise it's duplicated
            if original_url and original_url != normalized:
                logger.info(
                    f"Duplicate content: {normalized} "
                    f"(same as {original_url})"
                )
                crawl_stats["duplicates"] += 1

        except Exception:
            logger.exception(
                f"Failed duplicate detection for {base}"
            )

        # record page statistics for assignment
        try:
            analytics.record_page(normalized, soup)

        except Exception:
            logger.exception(
                f"Failed to record statistics for {base}"
            )

    crawl_stats["processed"] += 1

    return list(links) # convert to list


def has_repeated_path(url):
    """
    Detect excessively deep paths or
    consecutive repeated path segments
    """
    parsed = urlparse(url)
    segments = [
        segment.lower()
        for segment in parsed.path.split("/")
        if segment
    ]

    # check for max path depth in general. not necessarily repeated
    if len(segments) > MAX_PATH_DEPTH:
        return True

    # detect paths such as /events/events/events/
    repeated = 1
    for i in range(1, len(segments)):
        if segments[i] == segments[i - 1]:
            repeated += 1
            if repeated >= MAX_REPEATED_SEGMENTS:
                return True
        else:
            repeated = 1

    return False

def has_suspicious_query(url):
    """
    Detect URLs with unusually many query parameters
    no blacklisting specific query params (yet?)
    """
    parsed = urlparse(url)
    params = parse_qsl(
        parsed.query,
        keep_blank_values=True
    )

    return len(params) > MAX_QUERY_PARAMS


def is_valid(url):
    """
    Decide whether to crawl this url or not. 
    If you decide to crawl it, return True; otherwise return False.
    There are already some conditions that return False.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        # enforce max url length
        if not url or len(url) > MAX_URL_LENGTH:
            logger.debug(f"Invalid URL length: {url}")
            return False

        # Make sure we exact match the host or end with it
        host = parsed.hostname
        if not host or not any(
            host == d
            or host.endswith("." + d)
            for d in DOMAIN_WHITELIST
        ):
            return False

        # ignore unreadable filetypes
        if re.match(INVALID_EXTENSIONS, parsed.path.lower()):
            return False

        # reject excessively deep or repetitive paths
        if has_repeated_path(url):
            logger.debug(f"Suspicious path: {url}")
            return False

        # reject URLs with excessive query parameters
        if has_suspicious_query(url):
            logger.debug(f"Suspicious query: {url}")
            return False

        # avoid DokuWiki media-manager navigation traps
        if is_dokuwiki_trap(url):
            logger.debug(f"DokuWiki media trap: {url}")
            return False

        # otherwise its good
        return True

    # Error --> assume it's invalid
    except TypeError:
        logger.warning(f"TypeError for {url}")
        return False
    except ValueError:
        logger.warning(f"ValueError for {url}")
        return False


def is_dokuwiki_trap(url):
    """
    Avoid DokuWiki utility pages that can generate large
    numbers of low-information URL combinations.
    """
    parsed = urlparse(url)

    if parsed.hostname != "wiki.ics.uci.edu":
        return False

    if not parsed.path.startswith("/doku.php"):
        return False

    params = dict(parse_qsl(
        parsed.query,
        keep_blank_values=True
    ))

    # utility actions that don't represent regular wiki articles
    blocked_actions = {
        "media",
        "diff",
        "revisions",
        "edit",
    }

    if params.get("do") in blocked_actions:
        return True

    # historical versions of otherwise normal wiki pages
    if "rev" in params or "rev2[0]" in params or "rev2[1]" in params:
        return True

    return False


def normalize_url(url):
    try:
        if not url:
            return None

        url = url.strip()
        parsed = urlsplit(url)

        if parsed.scheme.lower() not in ("http", "https"):
            return None

        if not parsed.hostname:
            return None

        # only transformation we do is defragmentation
        # other changes could cause distinct URLs to be lumped together
        # any changes to this would be coupled to the frontier
        return urldefrag(url)[0]

    except (TypeError, ValueError):
        return None
