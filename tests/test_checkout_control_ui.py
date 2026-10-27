from copy import deepcopy
from streamlit.testing.v1 import AppTest


class Client:
    def __init__(self):
        self.state = dict(effective_mode='CLOSED', requested_mode='CLOSED', version=1,
                          changed_at='2026-10-27', audit_status='Versioned database transaction',
                          provider_readiness='Provider binding must be verified', test_ready=True,
                          test_blockers=[], stripe_test_credentials_configured=True,
                          stripe_live_credentials_configured=True, test_webhook_configured=True,
                          live_webhook_configured=True, frozen_plate_and_email_configuration_ready=True)
        self.writes = []
    def json(self,path):
        assert path == '/admin/checkout-control'
        return deepcopy(self.state)
    def checkout_mode_write(self,body):
        self.writes.append(body)
        if body['confirmation'] != 'APPLY ' + body['requested_mode']:
            return {'error':'Deliberate confirmation required'}
        self.state.update(effective_mode=body['requested_mode'],requested_mode=body['requested_mode'],
                          version=self.state['version']+1)
        return deepcopy(self.state)


ui_client = None


def test_owner_selector_deliberate_save_live_disabled_and_close():
    global ui_client
    ui_client = Client()
    app = AppTest.from_string('from test_checkout_control_ui import ui_client\nfrom manufacturing_control.checkout import run\nrun(ui_client)').run()
    assert not app.exception
    assert app.selectbox[0].options == ['CLOSED','TEST','LIVE']
    app.selectbox[0].set_value('TEST').run()
    assert app.metric[0].value == 'CLOSED'  # selection is not activation
    next(b for b in app.button if b.label == 'Save / Apply').click().run()
    assert app.error[0].value == 'Deliberate confirmation required'
    app.text_input[0].set_value('APPLY TEST').run()
    next(b for b in app.button if b.label == 'Save / Apply').click().run()
    assert app.metric[0].value == 'TEST'
    app.selectbox[0].set_value('LIVE').run()
    assert next(b for b in app.button if b.label == 'Save / Apply').disabled
    next(c for c in app.checkbox if c.label.startswith('I confirm:')).check().run()
    next(b for b in app.button if b.label == 'Close New Checkout').click().run()
    assert app.metric[0].value == 'CLOSED'
    assert ui_client.writes[-1]['requested_mode'] == 'CLOSED'
