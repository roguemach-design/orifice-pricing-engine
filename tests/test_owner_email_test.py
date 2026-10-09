from contextlib import contextmanager
from types import SimpleNamespace
import base64
import pytest
import requests
from frozen_plate import send_owner_test as testmail
from frozen_plate.presentation import mime_email
from frozen_plate.repository import WorkflowError, digest


@pytest.fixture
def scenario(monkeypatch):
    pdf = b"synthetic exact PDF"
    monkeypatch.setattr(testmail, "PDF_SHA256", digest(pdf))
    context = dict(order_id=testmail.ORDER_ID, line_id="line-1", drawing="OP-TEST",
                   revision="R1", quantity=1, filename="drawing.pdf")
    raw = mime_email(context, testmail.API_ORIGIN + "/approve/synthetic-test-token", pdf)
    objects = {"confirmation/" + testmail.DELIVERY_ID + ".eml": raw}
    def put(key, data):
        if key in objects:
            raise WorkflowError("already claimed")
        objects[key] = data
    plate = dict(id="plate", customer_id=testmail.OWNER_ID, current_revision=testmail.REVISION_ID)
    delivery = dict(revision_id=testmail.REVISION_ID, recipient_id=testmail.OWNER_ID,
                    pdf_id="pdf-id", mime_sha256=digest(raw))
    class Database:
        def execute(self, query, args):
            return SimpleNamespace(fetchone=lambda: plate if "frozen_plates " in query else delivery)
    @contextmanager
    def connect():
        yield Database()
    repo = SimpleNamespace(connect=connect,
        _verified=lambda db, revision: (
            dict(plate_id="plate", number=1),
            {"pdf": dict(id="pdf-id", sha256=digest(pdf), filename="drawing.pdf")},
            {"pdf": pdf}), storage=SimpleNamespace(get=objects.__getitem__, put=put))
    env = dict(APP_ENV="staging", RENDER_SERVICE_ID="srv-d9ritcijobas73didpbg",
               FROZEN_PLATE_EMAIL_MODE="capture", SENDGRID_API_KEY="fake-provider-key")
    return repo, env, objects, pdf


def test_owner_email_exact_pdf_fixed_recipient_and_single_attempt(scenario):
    repo, env, objects, pdf = scenario
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=202)
    assert testmail.run(repository=repo, environ=env, post=post)["sent"] is False
    assert not calls
    assert testmail.run(send=True, repository=repo, environ=env, post=post)["provider_accepted"]
    payload = calls[0][1]["json"]
    assert payload["personalizations"] == [{"to": [{"email": testmail.RECIPIENT}]}]
    assert len(payload["attachments"]) == 1
    assert base64.b64decode(payload["attachments"][0]["content"]) == pdf
    assert payload["tracking_settings"]["click_tracking"]["enable"] is False
    with pytest.raises(WorkflowError):
        testmail.run(send=True, repository=repo, environ=env, post=post)
    assert len(calls) == 1
    assert env["FROZEN_PLATE_EMAIL_MODE"] == "capture"


@pytest.mark.parametrize("field,value", [("APP_ENV", "production"),
    ("RENDER_SERVICE_ID", "other-service"), ("FROZEN_PLATE_EMAIL_MODE", "send"),
    ("SENDGRID_API_KEY", ""), ("FROM_EMAIL", "other@example.com")])
def test_owner_email_rejects_unsafe_environment_before_any_send(scenario, field, value):
    repo, env, objects, pdf = scenario
    env[field] = value
    def no_send(*args, **kwargs):
        pytest.fail("unsafe provider call")
    with pytest.raises(WorkflowError):
        testmail.run(send=True, repository=repo, environ=env, post=no_send)
    assert testmail.JOURNAL + "claimed.json" not in objects


def test_owner_email_unknown_provider_outcome_blocks_retry(scenario):
    repo, env, objects, pdf = scenario
    calls = []
    def timeout(*args, **kwargs):
        calls.append(True)
        raise requests.Timeout("sensitive provider details")
    with pytest.raises(WorkflowError, match="outcome unknown"):
        testmail.run(send=True, repository=repo, environ=env, post=timeout)
    with pytest.raises(WorkflowError, match="already claimed"):
        testmail.run(send=True, repository=repo, environ=env, post=timeout)
    assert len(calls) == 1
