"""Photo upload pipeline (Jahnavi): validation, OpenCV re-encoding, limits, storage and access control."""
import io

import cv2
import numpy as np
import pytest

from app.core.config import settings
from app.services import images

BODY = {"block": "A", "floor": "1", "description": "The ceiling fan in the classroom stopped working"}


@pytest.fixture(autouse=True, params=["opencv", "pillow"])
def _env(monkeypatch, request):
    """Every test here runs twice: with OpenCV and with the Pillow fallback used on Vercel."""
    monkeypatch.setenv("CAMPUSNOVA_AUTO_ASSIGN", "0")
    if request.param == "pillow":
        monkeypatch.setattr(images, "cv2", None)
    elif images.cv2 is None:
        pytest.skip("OpenCV not installed")


def png(w=200, h=120, seed=0) -> bytes:
    """A smooth, seed-dependent gradient (compresses well, so large dimensions stay small in bytes)."""
    x = np.linspace(0, 255, w, dtype=np.float32)[None, :].repeat(h, 0)
    y = np.linspace(0, 255, h, dtype=np.float32)[:, None].repeat(w, 1)
    img = np.stack([x, y, (x + y + seed * 37) % 256], axis=2).astype(np.uint8)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def jpg(w=200, h=120, seed=0) -> bytes:
    rng = np.random.default_rng(seed)
    ok, buf = cv2.imencode(".jpg", rng.integers(0, 255, (h, w, 3), dtype=np.uint8))
    return buf.tobytes()


@pytest.fixture()
def complaint(client, auth, users):
    return client.post("/complaints", json=BODY, headers=auth(users["faculty"])).json()


def upload(client, h, cid, data, name="photo.jpg", ctype="image/jpeg"):
    return client.post(f"/complaints/{cid}/images", files={"file": (name, io.BytesIO(data), ctype)}, headers=h)


# ------------------------------------------------------------------ pipeline unit tests
def test_process_image_reencodes_resizes_and_thumbnails():
    p = images.process_image(png(3200, 2400))
    assert max(p.width, p.height) == images.MAX_SIDE and p.content_type == "image/jpeg"
    thumb = cv2.imdecode(np.frombuffer(p.thumb, np.uint8), cv2.IMREAD_COLOR)
    assert max(thumb.shape[:2]) == images.THUMB_SIDE and len(p.sha256) == 64


def test_small_images_are_not_upscaled():
    p = images.process_image(jpg(100, 80))
    assert (p.width, p.height) == (100, 80)


def test_exif_and_appended_payloads_are_stripped():
    data = jpg() + b"<?php system($_GET['c']); ?>"  # polyglot: valid JPEG with a payload appended
    out = images.process_image(data).data
    assert b"<?php" not in out and b"Exif" not in out


@pytest.mark.parametrize("data,status", [
    (b"", 400), (b"GIF89a" + b"0" * 100, 415), (b"just text", 415), (b"%PDF-1.4 fake", 415), (b"MZ\x90\x00" + b"0" * 50, 415),
    (b"\xff\xd8\xff\xe0" + b"garbage" * 20, 400),  # right magic bytes, undecodable body
    (b"\x89PNG\r\n\x1a\n" + b"truncated", 400),
])
def test_bad_files_are_rejected(data, status):
    with pytest.raises(images.ImageRejected) as e:
        images.process_image(data)
    assert e.value.status_code == status


def test_truncated_real_jpeg_is_handled_without_crashing():
    data = jpg(400, 300)
    try:
        images.process_image(data[: len(data) // 2])
    except images.ImageRejected:
        pass  # either rejected or decoded partially: both are acceptable, a crash is not


def test_size_limit(monkeypatch):
    with pytest.raises(images.ImageRejected) as e:
        images.process_image(jpg(), max_bytes=100)
    assert e.value.status_code == 413


def test_tiny_images_rejected():
    with pytest.raises(images.ImageRejected):
        images.process_image(png(4, 4))


# ------------------------------------------------------------------ API
def test_upload_and_download(client, auth, users, complaint):
    h = auth(users["faculty"])
    r = upload(client, h, complaint["id"], png(), name="../../etc/passwd.png")
    assert r.status_code == 201 and r.json()["content_type"] == "image/jpeg" and r.json()["original_name"] == "passwd.png"
    img_id = r.json()["id"]
    got = client.get(f"/complaints/images/{img_id}/file", headers=h)
    assert got.status_code == 200 and got.content[:3] == b"\xff\xd8\xff"
    thumb = client.get(f"/complaints/images/{img_id}/file", params={"thumbnail": "true"}, headers=h)
    assert thumb.status_code == 200 and len(thumb.content) < len(got.content)
    detail = client.get(f"/complaints/{complaint['id']}", headers=h).json()
    assert [i["id"] for i in detail["images"]] == [img_id]


def test_content_type_and_extension_are_not_trusted(client, auth, users, complaint):
    h = auth(users["faculty"])
    assert upload(client, h, complaint["id"], b"<html>hi</html>", name="x.jpg", ctype="image/jpeg").status_code == 415
    assert upload(client, h, complaint["id"], jpg(), name="x.exe", ctype="application/octet-stream").status_code == 201  # real JPEG


def test_duplicate_photo_and_max_count(client, auth, users, complaint):
    h = auth(users["faculty"])
    assert upload(client, h, complaint["id"], png(seed=1)).status_code == 201
    assert upload(client, h, complaint["id"], png(seed=1)).status_code == 409
    for i in range(2, 6):
        assert upload(client, h, complaint["id"], png(seed=i)).status_code == 201
    over = upload(client, h, complaint["id"], png(seed=99))
    assert over.status_code == 409 and "at most" in over.json()["error"]["message"]


def test_oversized_upload_is_413(client, auth, users, complaint, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    assert upload(client, auth(users["faculty"]), complaint["id"], png()).status_code == 413


def test_only_the_reporter_or_admin_can_upload_or_view(client, auth, users, complaint):
    assert upload(client, auth(users["staff"]), complaint["id"], png()).status_code == 403
    assert upload(client, auth(users["electrician"]), complaint["id"], png()).status_code == 403
    r = upload(client, auth(users["admin"]), complaint["id"], png(seed=5))
    assert r.status_code == 201
    assert client.get(f"/complaints/images/{r.json()['id']}/file", headers=auth(users["staff"])).status_code == 403
    assert client.get(f"/complaints/images/{r.json()['id']}/file").status_code == 401
    assert client.get("/complaints/images/9999/file", headers=auth(users["admin"])).status_code == 404
    assert upload(client, auth(users["faculty"]), 9999, png()).status_code in (403, 404)


def test_missing_file_field_is_422(client, auth, users, complaint):
    r = client.post(f"/complaints/{complaint['id']}/images", headers=auth(users["faculty"]))
    assert r.status_code == 422


def test_photos_live_in_the_database_not_on_disk(client, auth, users, complaint, db, tmp_path, monkeypatch):
    from app.models import ComplaintImage

    monkeypatch.chdir(tmp_path)
    r = upload(client, auth(users["faculty"]), complaint["id"], png(seed=3))
    row = db.get(ComplaintImage, r.json()["id"])
    assert row.data[:3] == b"\xff\xd8\xff" and row.thumb_data and row.size_bytes == len(row.data)
    assert list(tmp_path.iterdir()) == []  # nothing was written to the file system
