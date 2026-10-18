"""A connector that lives outside kb/: proves new ingestors need no core change."""
from kb.core.ports import Connector, FetchedItem


class DummyConnector(Connector):
    name = "dummy"

    def list(self):
        return ["a", "b"]

    def fetch(self, ref, dest_dir):
        dest_dir.mkdir(parents=True, exist_ok=True)
        p = dest_dir / f"{ref}.txt"; p.write_text(ref)
        return FetchedItem(path=p, title=ref, kind="document", ref=ref)
