class Store:
    def __init__(self, path):
        self.path = path

    def create(self, title, tags=None, idempotency_key=None):
        raise NotImplementedError

    def get(self, item_id):
        raise NotImplementedError

    def list(self, status=None, tag=None, query=None, limit=20, offset=0):
        raise NotImplementedError

    def update(self, item_id, expected_version, title=None, status=None, tags=None):
        raise NotImplementedError

    def delete(self, item_id, expected_version):
        raise NotImplementedError

    def add_comment(self, item_id, text, expected_version):
        raise NotImplementedError

    def export_snapshot(self):
        raise NotImplementedError

    def import_snapshot(self, snapshot):
        raise NotImplementedError
