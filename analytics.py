import re
import shelve
import hashlib

from collections import Counter, defaultdict
from urllib.parse import urlparse, urldefrag


class Analytics:
    def __init__(self, stopwords, save_file="analytics.shelve"):
        # save analytics to a file using shelve, similar to frontier
        self.save = shelve.open(save_file)

        self.stopwords = {
            word.strip().lower()
            for word in stopwords
        }

    def record_page(self, url, soup, override=False):
        """
        Record statistics (word count, word frequencies) per page
        Skips already recorded values (unless override=True)
        """
        # defrag again for redundancy
        url = urldefrag(url)[0]
        urlhash = hashlib.sha256(url.encode("utf-8")).hexdigest()

        if urlhash in self.save and not override:
            return

        # remove elements that do not contain useful visible text
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)

        # count all words for the longest page statistic
        # treat a word as any alphanumeric sequence of characters, similar to assignment 1
        words = re.findall(r"[a-z0-9]+", text.lower())
        word_count = len(words)

        # exclude stopwords and tokens shorter than 3 characters
        # for the top 50 word frequency statistic
        frequencies = Counter(
            word for word in words
            if len(word) >= 3
            and word not in self.stopwords
        )

        # save the page's statistics
        # frequencies are saved across each page,
        # and will be added back up when generating report
        self.save[urlhash] = {
            "url": url,
            "word_count": word_count,
            "frequencies": frequencies,
        }
        self.save.sync()

    def generate_report(self):
        """
        Generate the four required assignment statistics
        1) how many unique pages
        2) longest page in words
        3) 50 most common words excluding stopwords
        4) subdomains under ics.uci.edu
        """
        total_pages = 0
        longest_url = None
        longest_count = 0

        word_frequencies = Counter()
        subdomain_counts = defaultdict(int)

        # aggregate statistics from all saved pages
        for page in self.save.values():
            url = page["url"]
            word_count = page["word_count"]

            total_pages += 1

            # track longest page
            if longest_url is None or word_count > longest_count:
                longest_url = url
                longest_count = word_count

            # aggregate word frequencies
            # + backwards compatibility before length 3+ filtered out
            word_frequencies.update({
                word: count
                for word, count in page["frequencies"].items()
                if len(word) >= 3
            })

            # track ICS subdomains
            hostname = urlparse(url).hostname

            if hostname and hostname.endswith(".ics.uci.edu"):
                subdomain_counts[hostname] += 1

        print(f"Total unique pages: {total_pages}")
        print()

        print(f"\nLongest page: {longest_url}")
        print(f"Word count: {longest_count}")
        print()

        print("\nTop 50 words:")
        for word, count in word_frequencies.most_common(50):
            print(f"{word}: {count}")
        print()

        print("\nICS subdomains:")
        for hostname in sorted(subdomain_counts):
            print(f"http://{hostname}, {subdomain_counts[hostname]}")
        print()
        print(f"\nTotal ICS subdomains: {len(subdomain_counts)}")

    def generate_diagnostics(self):
        """
        get additional analytics for debugging/investigating traps
        """
        pages = list(self.save.values())

        # 1. longest pages in the crawl
        print("\nTop 20 longest pages:")

        longest_pages = sorted(
            pages,
            key=lambda page: page["word_count"],
            reverse=True
        )[:20]

        for page in longest_pages:
            print(f"{page['word_count']} {page['url']}")

        # 2. inspect word frequencies on the longest page
        if longest_pages:
            longest = longest_pages[0]

            print("\nLongest page top words:")
            for word, count in longest["frequencies"].most_common(30):
                print(f"{word}: {count}")

        # 3. count known trap URL patterns
        # we want to see if these are being hit
        patterns = [
            "do=diff",
            "idx=",
            "version=",
            "tribe-bar-date=",
            "/day/",
        ]

        print("\nPotential trap URLs:")
        for pattern in patterns:
            count = sum(
                pattern in page["url"].lower()
                for page in pages
            )
            print(f"{pattern}: {count}")

        # 4. inspect coverage of the required domains
        domain_counts = Counter()

        for page in pages:
            hostname = urlparse(page["url"]).hostname or ""

            if (
                hostname == "ics.uci.edu"
                or hostname.endswith(".ics.uci.edu")
            ):
                domain_counts["ics.uci.edu"] += 1

            elif (
                hostname == "cs.uci.edu"
                or hostname.endswith(".cs.uci.edu")
            ):
                domain_counts["cs.uci.edu"] += 1

            elif (
                hostname == "informatics.uci.edu"
                or hostname.endswith(".informatics.uci.edu")
            ):
                domain_counts["informatics.uci.edu"] += 1

            elif (
                hostname == "stat.uci.edu"
                or hostname.endswith(".stat.uci.edu")
            ):
                domain_counts["stat.uci.edu"] += 1

        print("\nDomain coverage:")
        for domain in (
            "ics.uci.edu",
            "cs.uci.edu",
            "informatics.uci.edu",
            "stat.uci.edu",
        ):
            print(f"{domain}: {domain_counts[domain]}")

    def close(self):
        self.save.close()
