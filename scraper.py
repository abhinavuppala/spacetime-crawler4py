import re
import logging

from urllib.parse import urlparse, urldefrag, urljoin
from bs4 import BeautifulSoup

from utils import get_logger

DOMAIN_WHITELIST = (
    "ics.uci.edu",
    "cs.uci.edu",
    "informatics.uci.edu",
    "stat.uci.edu",
)

logger = get_logger(f"SCRAPER") # shared logger
logger.setLevel(logging.DEBUG) # DEBUG for development

def scraper(url, resp):
    try:
        links = extract_next_links(url, resp)
        return [link for link in links if is_valid(link)]
    except Exception:
        # wrap in a try except to log errors better
        # logger.exception already includes stack trace and logger name has URL
        logger.exception(f"Failed to scrape url {url}")
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
        return []

    base = resp.raw_response.url or url
    links = set()

    # look for all <a> tags with hrefs to find outgoing links
    soup = BeautifulSoup(resp.raw_response.content, "html.parser")
    for a in soup.find_all("a", href=True):
        try:
            # urljoin accounts for absolute or relative links
            abs_link = urljoin(base, a["href"].strip())
            # removes any # sections from the URL
            links.add(urldefrag(abs_link)[0])
        except ValueError: # skip any malformed links
            continue
    return list(links) # convert to list


def is_valid(url):
    """
    Decide whether to crawl this url or not. 
    If you decide to crawl it, return True; otherwise return False.
    There are already some conditions that return False.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in set(["http", "https"]):
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
        return not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", parsed.path.lower())

    # Error --> assume it's invalid
    except TypeError:
        logger.warning(f"TypeError for {url}")
        return False
    except ValueError:
        logger.warning(f"ValueError for {url}")
        return False
