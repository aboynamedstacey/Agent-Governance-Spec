"""Incremental audit-head verification for a trusted, serialized local adapter.

Per-request work is proportional only to entries appended since the previous
check, not to the entire audit history. Periodic full verification remains
essential: local tail checks cannot detect arbitrary edits to old entries or
replacement of both the log and its checkpoint. Production requires an
independently protected, durable head and external checkpoints.
"""
from reference_algorithms import hash_entry, verify_chain


class AuditHeadGuard:
    def __init__(self, chain, genesis, algorithm="SHA256"):
        self.chain = chain
        self.genesis = genesis
        self.algorithm = algorithm
        self.trusted_length = 0
        self.trusted_hash = genesis["signature"]
        self.quarantined = False

    def check_incremental(self):
        if self.quarantined:
            return False
        if len(self.chain) < self.trusted_length:
            self.quarantined = True
            return False
        if self.trusted_length and (
                self.chain[self.trusted_length - 1].get("chain_hash") != self.trusted_hash):
            self.quarantined = True
            return False
        previous = self.trusted_hash
        try:
            for entry in self.chain[self.trusted_length:]:
                expected = hash_entry(self.algorithm, previous, entry)
                if entry.get("chain_hash") != expected:
                    self.quarantined = True
                    return False
                previous = expected
        except (ValueError, KeyError, TypeError, UnicodeError):
            self.quarantined = True
            return False
        self.trusted_length = len(self.chain)
        self.trusted_hash = previous
        return True

    def verify_full(self):
        """Off-path deep verification; any failure blocks subsequent actions."""
        if self.quarantined:
            return False
        try:
            valid, _ = verify_chain(self.chain, self.algorithm, self.genesis)
        except (ValueError, KeyError, TypeError, UnicodeError):
            valid = False
        if not valid:
            self.quarantined = True
            return False
        expected = (self.chain[self.trusted_length - 1]["chain_hash"]
                    if self.trusted_length else self.genesis["signature"])
        if len(self.chain) < self.trusted_length or expected != self.trusted_hash:
            self.quarantined = True
            return False
        self.trusted_length = len(self.chain)
        self.trusted_hash = (self.chain[-1]["chain_hash"]
                             if self.chain else self.genesis["signature"])
        return True
