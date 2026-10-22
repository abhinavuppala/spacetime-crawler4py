import hashlib
import shelve


class DuplicateDetector:
    def __init__(self, save_file="duplicates.shelve"):
        self.save = shelve.open(save_file)

    def check_duplicate(self, url, text):
        """
        Check if the page's text has been seen before
        return None if its new, or the original URL if it's not
        """
        # normalize whitespace before hashing
        text = " ".join(text.split())
        content_hash = hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()

        if content_hash in self.save:
            return self.save[content_hash]

        # save the first URL associated with this content
        self.save[content_hash] = url
        self.save.sync()
        return None

    def close(self):
        self.save.close()
