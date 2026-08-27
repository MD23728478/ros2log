import config

from backend.app import create_app


def test_pages_and_api():
    config.PERSIST_DATABASE = False
    config.DATABASE = "file:test?mode=memory&cache=shared"
    client = create_app().test_client()

    page = client.get("/")
    assert page.status_code == 200
    assert b"Hello, World!" in page.data

    api = client.get("/api/hello")
    assert api.status_code == 200
    assert api.get_json() == {"message": "Hello from the API"}
